from datetime import datetime
import random
from typing import Optional

from allauth.account.signals import user_signed_up
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail, EmailMessage
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.template.loader import get_template
from phonenumber_field.phonenumber import to_python

from abmci.notifications.fcm import send_to_topic
from abmci.services.nearest_church import assign_nearest_eglise_if_missing
from abmci.services.notifications import notify_new_comment
from abmci.utils.orange_sms import send_sms
from event.models import Evenement
from fidele.models import Fidele, PrayerRequest, PrayerComment, ProblemReport, Role
from django.dispatch import Signal
from abmci.tasks import send_problem_sms_to_pastors, notify_problem_changed, notify_comment_created_task, \
    generate_recurrences_task

notify = Signal()


def qlook():
    qlook = ("QL" + str(random.randrange(0, 999999999, 1)) + "SAH")
    return qlook


@receiver(post_save, sender=User)
def create_fidele(sender, instance, created, **kwargs):
    if created:
        fidele = Fidele.objects.create(user=instance)


@receiver(user_signed_up)
def create_user_profile_completion(sender, request, user, **kwargs):
    from .models import Fidele, UserProfileCompletion

    # Créer le profil Fidele s’il n’existe pas
    fidele, created = Fidele.objects.get_or_create(user=user)

    # Créer ou récupérer l'objet de suivi
    UserProfileCompletion.objects.get_or_create(user=user)

    # Vérifier les champs requis (ex: birthdate, sexe, phone)
    incomplete = any([
        not fidele.birthdate,
        not fidele.phone,
        not fidele.sexe,
        # ajoute ici d'autres champs obligatoires
    ])

    if incomplete:
        # Marquer dans la session qu'on doit compléter le profil
        request.session['complete_profile_required'] = True


# prayers/signals.py
@receiver(post_save, sender=PrayerRequest)
def notify_new_prayer(sender, instance: PrayerRequest, created, **kwargs):
    if not created:
        return
    title = 'Nouveau sujet de prière'
    body = instance.title[:120]
    data = {'type': 'prayer', 'prayer_id': instance.id}
    # Topic global
    send_to_topic('prayers', title, body, data)
    # Optionnel: topic par église
    # send_to_topic(f'eglise_{instance.user.fidele.eglise_id}', title, body, data)
    # In-app (persistante) pour followers/église par ex. (à adapter)
    # for user in <cible>:
    #     Notification.objects.create(user=user, title=title, body=body, data=data)


@receiver(post_save, sender=PrayerComment)
def on_comment_created(sender, instance: PrayerComment, created: bool, **kwargs):
    if not created:
        return
    # instance.prayer doit être accessible (FK)
    notify_new_comment(instance.prayer, instance)


@receiver(post_save, sender=Fidele)
def set_nearest_church_on_create(sender, instance: Fidele, created: bool, **kwargs):
    """
    Après création (ou update), si aucune église et qu’on a des coordonnées,
    on affecte la plus proche. On limite aux créations (ou seulement si encore vide).
    """
    # Tu peux restreindre à 'created is True' si tu veux éviter les updates :
    # if not created: return
    try:
        updated = assign_nearest_eglise_if_missing(instance, max_radius_km=50)  # par ex. 50 km
        # Optionnel: logger si updated
        # if updated:
        #     logger.info("Fidele %s affecté à l’église %s", instance.pk, instance.eglise_id)
    except Exception as e:
        # Evite que le signal casse la transaction ; remplace par un logger
        print(f"[signals] assign_nearest_eglise_if_missing error: {e!r}")


@receiver(post_save, sender=ProblemReport)
def problem_report_post_save(sender, instance, created, **kwargs):
    if not created:
        return

    def _enqueue():
        # évite import direct -> pas de circular import
        from abmci.tasks import notify_problem_created
        notify_problem_created.delay(instance.id)

    # Sécu: on ne publie qu'après commit
    transaction.on_commit(_enqueue)


def _fmt_date(d):
    if not d:
        return "—"
    # JJ/MM/AAAA
    return d.strftime("%d/%m/%Y")


@receiver(post_save, sender=Evenement)
def schedule_recurrences_on_create(sender, instance: "Evenement", created, **kwargs):
    """
    Planifie la génération des récurrences lorsque:
    - un Evenement est CRÉÉ et marqué is_recurrent=True
    - OU quand on bascule un existant en récurrent (optionnel: à activer si besoin)
    """
    # Ne génère que pour les PARENTS (tes enfants ont is_recurrent=False)
    if not instance.is_recurrent:
        return

    # Déclenche seulement à la création
    if created:
        transaction.on_commit(lambda: generate_recurrences_task.delay(instance.id))
        return

    # (Optionnel) Si tu veux aussi déclencher quand on édite un event et qu'il devient récurrent:
    # Astuce simple : si aucune occurrence enfant n'existe encore, on peut générer.
    if not instance.children.exists():
        transaction.on_commit(lambda: generate_recurrences_task.delay(instance.id))


# @receiver(post_save, sender=ProblemReport)
# def notify_pastors_on_problem_created(sender, instance: ProblemReport, created, **kwargs):
#     if not created:
#         return
#
#     # Récupère les pasteurs de la même église
#     try:
#         role_pasteur = Role.objects.get(code='PASTEUR')
#     except Role.DoesNotExist:
#         return  # aucun rôle pasteur configuré
#
#     qs = Fidele.objects.filter(
#         roles=role_pasteur,
#         eglise=instance.eglise,
#         phone__isnull=False,
#     ).distinct()
#
#     reporter_name = getattr(instance.reporter.user, "first_name", "") + " " + getattr(instance.reporter.user, "last_name", "")
#     reporter_name = reporter_name.strip() or "Un fidèle"
#     due = _fmt_date(instance.due_date)
#
#     # Message
#     msg = (
#         f"Bonjour, le fidèle {reporter_name} a signalé « {instance.title} » "
#         f"(échéance: {due}). Merci de le contacter."
#     )
#
#     # Envoie à chaque pasteur
#     for f in qs:
#         if not f.phone:
#             continue
#         # phone est un PhoneNumber -> convertir en E164 string
#         p = to_python(f.phone)
#         if not p:
#             continue
#         to = p.as_e164  # ex: +2250700000000
#         try:
#             send_sms(to, msg)
#         except Exception:
#             # log silencieux, ne bloque pas la requête
#             import logging
#             logging.getLogger(__name__).exception("Échec envoi SMS à %s", to)


@receiver(post_save, sender=ProblemReport)
def notify_pastors_on_problem(sender, instance: ProblemReport, created, **kwargs):
    """
    Dès qu’un nouveau problème est signalé, planifie l’envoi de SMS aux pasteurs via Celery.
    """
    if created:
        # on décale un peu (5s) pour s'assurer que tout est bien commit
        send_problem_sms_to_pastors.apply_async(args=[instance.id], countdown=5)


def _assignee_label(fid) -> str:
    """
    Libellé humain pour l'assigné.
    """
    if not fid:
        return "Non assigné"
    full = fid.user.get_full_name().strip()
    return full or fid.user.username or f"Fidèle #{fid.pk}"


@receiver(pre_save, sender=ProblemReport)
def _store_previous_values(sender, instance: ProblemReport, **kwargs):
    """
    Avant sauvegarde, on mémorise les anciennes valeurs pour comparaison en post_save.
    """
    if not instance.pk:
        # création: pas de comparaison
        instance.__old_status = None
        instance.__old_assignee_id = None
        return

    try:
        old = ProblemReport.objects.only("status", "assignee").get(pk=instance.pk)
        instance.__old_status = old.status
        instance.__old_assignee_id = old.assignee_id
    except ProblemReport.DoesNotExist:
        instance.__old_status = None
        instance.__old_assignee_id = None


@receiver(post_save, sender=ProblemReport)
def _notify_on_change(sender, instance: ProblemReport, created: bool, **kwargs):
    """
    Après sauvegarde, si statut ou assigné a changé, on notifie le reporter via FCM (asynchrone).
    """
    # On ne notifie pas ici lors de la création : tu as déjà une task de création.
    if created:
        return

    old_status: Optional[str] = getattr(instance, "__old_status", None)
    old_assignee_id: Optional[int] = getattr(instance, "__old_assignee_id", None)

    changed: dict[str, str] = {}

    # Statut changé ?
    if old_status is not None and old_status != instance.status:
        changed["status"] = instance.get_status_display()

    # Assigné changé ?
    if old_assignee_id != instance.assignee_id:
        changed["assignee"] = _assignee_label(instance.assignee)

    if changed:
        # Appel asynchrone Celery
        notify_problem_changed.delay(instance.pk, changed)


@receiver(post_save, sender=PrayerComment)
def on_prayer_comment_created(sender, instance: PrayerComment, created: bool, **kwargs):
    if not created:
        return

    def _enqueue():
        author = instance.user.get_full_name() or instance.user.username or None
        notify_comment_created_task.delay(
            prayer_id=instance.prayer_id,
            comment_id=instance.id,
            author_name=author,
            dry_run=False,
        )

    # ⚠️ Après COMMIT pour éviter les courses DB
    transaction.on_commit(_enqueue)
