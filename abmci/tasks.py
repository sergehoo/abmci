from celery import shared_task, group
from django.core.management import call_command
from django.db import transaction

from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string

from event.models import Evenement, ParticipationEvenement
from event.services.events import generate_recurrences_for_parent
from fidele.models import Eglise
from fidele.views import process_account_deletion_request
from fidele.vod_smart import pick_smart_daily_verse_for_eglise
# from .models import ParticipationEvenement
from .notifications.fcm import send_to_topic


@shared_task
def send_event_reminders():
    # Trouver les événements à venir dans les prochains jours
    upcoming_events = Evenement.objects.filter(
        date_debut__gt=timezone.now(),
        date_debut__lte=timezone.now() + timezone.timedelta(days=7)
    )

    for event in upcoming_events:
        participants = ParticipationEvenement.objects.filter(evenement=event)

        for participation in participants:
            # Envoyer une notification à chaque participant
            subject = f"Rappel: {event.titre}"
            message = render_to_string('emails/event_reminder.txt', {
                'event': event,
                'participation': participation
            })

            send_mail(
                subject,
                message,
                'no-reply@votredomaine.com',
                [participation.fidele.user.email],
                fail_silently=False,
            )



@shared_task
def update_daily_verses_for_all_eglisess(version_code="LSG", language="fr"):
    """
    Tâche planifiée (via django-celery-beat) qui sélectionne et enregistre
    un verset pour chaque église (variation déterministe + anti-répétition).
    """
    count = 0
    today = timezone.localdate()
    for e in Eglise.objects.all():
        try:
            with transaction.atomic():
                pick_smart_daily_verse_for_eglise(
                    eglise=e,
                    version_code=version_code,
                    language=language,
                    on_date=today,
                )
                count += 1
        except Exception as ex:
            # logge toi-même si besoin
            print(f"[VOD] {e.id}: {ex}")
    return count
@shared_task
def task_process_account_deletion_request(req_id):
    process_account_deletion_request(req_id)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def generate_recurrences_task(self, parent_id: int):
    try:
        parent = Evenement.objects.get(pk=parent_id)
    except Evenement.DoesNotExist:
        return {"created": 0, "children": []}

    created_ids = generate_recurrences_for_parent(parent)

    # Enchaîner la génération QR + resize pour les nouveaux
    # (on évite d'ouvrir/écrire des fichiers pendant le bulk)
    if created_ids:
        # en groupes/chunks de 200
        chunks = [created_ids[i:i+200] for i in range(0, len(created_ids), 200)]
        group(generate_qr_and_resize_chunk.s(chunk) for chunk in chunks).delay()

    return {"created": len(created_ids), "children": created_ids}

@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def generate_qr_and_resize_chunk(self, ids: list[int]):
    qs = Evenement.objects.filter(id__in=ids)
    for ev in qs:
        # QR
        if not ev.qr_code:
            ev.generate_and_save_qr_code(ev.code)
        # Resize banner si présente
        if ev.banner:
            try:
                from PIL import Image
                img = Image.open(ev.banner.path)
                new_size = (1420, 560)
                img = img.resize(new_size, Image.LANCZOS)
                img.save(ev.banner.path)
            except Exception:
                pass
        ev.save(update_fields=["qr_code"])  # bannière écrite en place, pas besoin d’update_field