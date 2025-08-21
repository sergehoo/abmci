# fidele/management/commands/update_daily_verse_and_notify.py
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Tuple, List

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from fidele.models import Eglise
from fidele.vod_service import pick_daily_verse_from_db
from abmci.notifications.fcm import (
    send_verse_to_eglise_topic,
)


def _norm(s: str | None) -> str:
    # Compacte espaces pour éviter les faux "pas de changement"
    return " ".join((s or "").split())


class Command(BaseCommand):
    help = (
        "Met à jour le Verset du Jour pour toutes les églises (sélection intelligente) "
        "et envoie une notification Firebase FCM aux églises concernées."
    )

    def add_arguments(self, parser):
        parser.add_argument("--bibleversion", default="LSG", help="Version biblique (ex: LSG)")
        parser.add_argument("--lang", default="fr", help="Langue (ex: fr)")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ne persiste rien et n’envoie aucune notification (simulation).",
        )
        parser.add_argument(
            "--force-notify",
            action="store_true",
            help="Force l’envoi de notification même si le verset n’a pas changé aujourd’hui.",
        )
        parser.add_argument(
            "--force-update",
            action="store_true",
            help="Force la mise à jour DB (verse_date/texte/référence) même si inchangé.",
        )

    def handle(self, *args, **opts):
        version: str = opts["bibleversion"]
        lang: str = opts["lang"]
        dry_run: bool = opts["dry_run"]
        force_notify: bool = opts["force_notify"]
        force_update: bool = opts["force_update"]

        today = timezone.localdate()

        eglises: List[Eglise] = list(Eglise.objects.all())
        if not eglises:
            self.stdout.write("Aucune église.")
            return

        # 1) Calcul du VDJ par église (service gère la sélection déterministe)
        computed: Dict[int, Dict] = {}
        for e in eglises:
            data = pick_daily_verse_from_db(
                version_code=version, language=lang, on_date=today, eglise=e
            )
            if not isinstance(data, dict) or "reference" not in data or "text" not in data:
                raise CommandError(
                    f"pick_daily_verse_from_db a renvoyé un payload invalide pour Eglise(id={e.id})."
                )
            computed[e.id] = data

        # 2) Détection changements + build des listes
        to_update: List[Eglise] = []
        to_notify: List[Tuple[int, Dict]] = []

        for e in eglises:
            d = computed[e.id]
            changed = (
                    e.verse_date != today
                    or _norm(e.verse_reference) != _norm(d["reference"])
                    or _norm(e.verse_du_jour) != _norm(d["text"])
            )

            if changed or force_update:
                # Mettre à jour en mémoire (bulk_update ensuite)
                e.verse_du_jour = d["text"]
                e.verse_reference = d["reference"]
                e.verse_date = today
                to_update.append(e)
                if changed or force_notify:
                    to_notify.append((e.id, d))
            elif force_notify:
                # Pas de MAJ DB, mais on notifie tout de même
                to_notify.append((e.id, d))

        # 3) Persistance + notifications (après commit) — support dry-run
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY-RUN] {len(to_update)} églises seraient mises à jour, "
                    f"{len(to_notify)} notifications seraient envoyées."
                )
            )
        else:
            with transaction.atomic():
                if to_update:
                    Eglise.objects.bulk_update(
                        to_update, ["verse_du_jour", "verse_reference", "verse_date"], batch_size=500
                    )

                if to_notify:
                    date_str = str(today)

                    def _send_batch(notify_items: List[Tuple[int, Dict]]):
                        ok = fail = 0
                        for eglise_id, d in notify_items:
                            try:
                                send_verse_to_eglise_topic(
                                    eglise_id,
                                    reference=d["reference"],
                                    text=d["text"],
                                    date_str=date_str,
                                    version=d.get("version", version),
                                    lang=d.get("language", lang),
                                    dry_run=False,
                                )
                                ok += 1
                            except Exception as ex:
                                fail += 1
                                self.stderr.write(f"[FCM][eglise_{eglise_id}] Échec envoi: {ex!r}")
                        self.stdout.write(f"[FCM] sent={ok}, failed={fail}")

                    # Envoi APRES commit
                    transaction.on_commit(lambda items=to_notify: _send_batch(items))

        # 4) Statistiques par contexte (le service renvoie DEFAULT)
        by_ctx = defaultdict(int)
        for d in computed.values():
            ctx = d.get("context_key", "DEFAULT")
            by_ctx[ctx] += 1
        details = ", ".join([f"{k}={v}" for k, v in sorted(by_ctx.items())])

        # 5) Sortie console
        updated_count = len(to_update)
        notified_count = len(to_notify)
        prefix = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}VDJ mis à jour pour {updated_count} églises (sur {len(eglises)}). "
                f"Notifications: {notified_count}. Contextes: {details}"
            )
        )
