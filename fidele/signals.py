from datetime import datetime
import random

from allauth.account.signals import user_signed_up
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail, EmailMessage
from django.db.models.signals import post_save, pre_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.template.loader import get_template

from abmci.notifications.fcm import send_to_topic
from abmci.services.notifications import notify_new_comment
from fidele.models import Fidele, PrayerRequest, PrayerComment
from django.dispatch import Signal

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