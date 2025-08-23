# fidele/management/commands/backfill_fideles_church.py
from django.core.management.base import BaseCommand
from django.db import transaction

from abmci.services.nearest_church import assign_nearest_eglise_if_missing
from fidele.models import Fidele


class Command(BaseCommand):
    help = "Affecte l’église la plus proche pour les fidèles sans église, si possible."

    def add_arguments(self, parser):
        parser.add_argument("--radius-km", type=float, default=50.0, help="Rayon max (km)")

    def handle(self, *args, **opts):
        radius = opts["radius_km"]
        qs = Fidele.objects.filter(eglise__isnull=True)
        total = qs.count()
        done = 0
        self.stdout.write(f"À traiter: {total} fidèle(s)")

        with transaction.atomic():
            for f in qs.iterator(chunk_size=500):
                if assign_nearest_eglise_if_missing(f, max_radius_km=radius):
                    done += 1

        self.stdout.write(self.style.SUCCESS(f"Assignations effectuées: {done}/{total}"))
