# vod/management/commands/send_vod.py
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone
from abmci.tasks import send_daily_vod


class Command(BaseCommand):
    help = "Envoie le Verset du Jour (VDJ) à toutes les églises pour la date donnée (YYYY-MM-DD)."

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("--date", type=str, help="YYYY-MM-DD (défaut: aujourd'hui)")
        parser.add_argument("--dry-run", action="store_true", help="N'envoie pas, affiche seulement")

    def handle(self, *args, **opts):
        date_str = opts.get("date") or str(timezone.localdate())
        dry = bool(opts.get("dry_run"))
        res = send_daily_vod.apply(kwargs={"when_date": date_str, "dry_run": dry}).get()
        self.stdout.write(self.style.SUCCESS(f"VDJ {date_str}: {res}"))
