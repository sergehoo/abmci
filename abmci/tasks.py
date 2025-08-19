from celery import shared_task
from django.core.management import call_command

# from abmci.celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string

from event.models import Evenement
from fidele.views import process_account_deletion_request
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
def task_update_verse_du_jour(version="LSG", lang="fr"):
    call_command("update_verse_du_jour", version=version, lang=lang)


@shared_task
def task_process_account_deletion_request(req_id):
    process_account_deletion_request(req_id)
