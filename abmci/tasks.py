from abmci.celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string

from event.models import Evenement
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
def push_verse_of_the_day(text: str, reference: str):
    title = 'Verset du jour'
    body = f'{text} — {reference}'
    data = {'type': 'verse'}
    send_to_topic('verse', title, body, data)