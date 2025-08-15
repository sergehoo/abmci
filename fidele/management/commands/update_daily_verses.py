# management/commands/update_daily_verses.py
from django.core.management.base import BaseCommand
from django.utils import timezone
import requests  # Pour récupérer des versets d'une API externe si besoin

from fidele.models import Eglise


class Command(BaseCommand):
    help = 'Update daily verses for all churches'

    def handle(self, *args, **options):
        for eglise in Eglise.objects.all():
            # Exemple avec une API externe
            response = requests.get('https://bible-api.com/random')
            if response.status_code == 200:
                data = response.json()
                eglise.verse_du_jour = data['text']
                eglise.verse_reference = data['reference']
                eglise.verse_date = timezone.now().date()
                eglise.save(update_fields=['verse_du_jour', 'verse_reference', 'verse_date'])