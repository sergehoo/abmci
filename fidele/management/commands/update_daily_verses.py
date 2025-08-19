# management/commands/update_daily_verses.py
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
import requests  # Pour récupérer des versets d'une API externe si besoin

from fidele.models import Eglise
from fidele.vod_service import get_or_create_vod_cache
from fidele.vod_smart import pick_smart_daily_verse


class Command(BaseCommand):
    help = "Met à jour le Verset du Jour pour toutes les églises (sélection intelligente)."

    def add_arguments(self, parser):
        parser.add_argument("--bibleversion", default="LSG", help="Version (ex: LSG)")
        parser.add_argument("--lang", default="fr", help="Langue (ex: fr)")

    def handle(self, *args, **opts):
        version = opts["bibleversion"]
        lang = opts["lang"]
        today = timezone.localdate()

        eglises = list(Eglise.objects.all())
        if not eglises:
            self.stdout.write("Aucune église.")
            return

        # 1) calcule un VDJ par église (le service va gérer le cache/context_key)
        computed = {}
        for e in eglises:
            data = pick_smart_daily_verse(version_code=version, language=lang, on_date=today, eglise=e)
            computed[e.id] = data

        # 2) applique en bulk
        for e in eglises:
            d = computed[e.id]
            e.verse_du_jour = d["text"]
            e.verse_reference = d["reference"]
            e.verse_date = today

        with transaction.atomic():
            Eglise.objects.bulk_update(eglises, ["verse_du_jour", "verse_reference", "verse_date"], batch_size=500)

        # Statistiques par contexte
        by_ctx = defaultdict(int)
        for d in computed.values():
            by_ctx[d["context_key"]] += 1

        details = ", ".join([f"{k}={v}" for k, v in sorted(by_ctx.items())])
        self.stdout.write(self.style.SUCCESS(
            f"VDJ mis à jour pour {len(eglises)} églises. Contextes: {details}"
        ))