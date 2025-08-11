# core/receivers.py
from django.dispatch import receiver

from fidele.models import Notification
from fidele.signals import notify


@receiver(notify)
def create_notification(sender, recipient, verb, actor=None, target_url=None, **kwargs):
    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb=verb,
        target_url=target_url
    )