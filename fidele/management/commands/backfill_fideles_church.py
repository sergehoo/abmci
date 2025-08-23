from django.core.management.base import BaseCommand
from django.utils import timezone

from abmci.services.nearest_church import assign_nearest_eglise_if_missing
from fidele.models import Fidele, FidelePosition

class Command(BaseCommand):
    help = "Assigne l’église la plus proche aux fidèles sans église, en se basant sur leur dernière position connue."

    def add_arguments(self, parser):
        parser.add_argument("--max-radius-km", type=float, default=50,
            help="Rayon max en km (par défaut 50 km)")
        parser.add_argument("--max-age-hours", type=int, default=72,
            help="Âge max des positions (heures)")
        parser.add_argument("--max-accuracy-m", type=float, default=1000,
            help="Précision max en mètres (par défaut 1000m)")
        parser.add_argument("--verbose", action="store_true",
            help="Affiche les détails des assignations")

    def handle(self, *args, **opts):
        radius_km = opts["max_radius_km"]
        max_age_hours = opts["max_age_hours"]
        max_accuracy_m = opts["max_accuracy_m"]
        verbose = opts["verbose"]

        cutoff = timezone.now() - timezone.timedelta(hours=max_age_hours)

        fideles = Fidele.objects.filter(eglise__isnull=True)
        self.stdout.write(f"À traiter: {fideles.count()} fidèle(s)")

        assigned = 0
        for f in fideles:
            pos = FidelePosition.objects.filter(
                fidele=f,
                captured_at__gte=cutoff,
                accuracy__lte=max_accuracy_m
            ).order_by("-captured_at").first()

            if not pos:
                if verbose:
                    self.stdout.write(f"- Fidele {f.id}: aucune position valable")
                continue

            ok = assign_nearest_eglise_if_missing(f, max_radius_km=radius_km)
            if ok:
                assigned += 1
                if verbose:
                    self.stdout.write(
                        f"✓ Fidele {f.id}: assigné à {f.eglise_id}"
                    )
            else:
                if verbose:
                    self.stdout.write(f"- Fidele {f.id}: pas d’église trouvée")

        self.stdout.write(
            self.style.SUCCESS(
                f"Assignations effectuées: {assigned}/{fideles.count()}"
            )
        )