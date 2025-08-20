from celery import shared_task
from django.core.management import call_command
from django.db import transaction

from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string

from event.models import Evenement
from fidele.models import Eglise
from fidele.views import process_account_deletion_request
from fidele.vod_smart import pick_smart_daily_verse_for_eglise
from .models import ParticipationEvenement
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
