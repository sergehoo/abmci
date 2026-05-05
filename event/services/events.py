# services/events.py
import logging
from typing import List

from django.db import transaction, connections
from event.models import Evenement

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 0xE71E51D  # clé arbitraire globale


def _pg_advisory_lock(cur, key):
    cur.execute("SELECT pg_advisory_lock(%s)", [key])


def _pg_advisory_unlock(cur, key):
    cur.execute("SELECT pg_advisory_unlock(%s)", [key])


def _ensure_qr_code(evt: Evenement) -> None:
    """
    Génère et attache le QR code d'une occurrence avant le bulk_create.
    bulk_create() ne déclenche PAS save(), donc seul le parent recevait son
    QR code. On force ici la génération sur chaque enfant avant l'insert :
    `qr_code.save(..., save=False)` persiste le fichier dans le storage et
    renseigne `instance.qr_code.name`, qui sera bien inséré par bulk_create.
    """
    if evt.qr_code:
        return
    try:
        evt.generate_and_save_qr_code(evt.code)
    except Exception as exc:  # noqa: BLE001
        # On n'échoue pas la série entière à cause d'un seul QR cassé.
        logger.warning("QR code generation failed for %s: %s", evt.code, exc)


def generate_recurrences_for_parent(
    parent: Evenement,
    max_occurrences: int = 1000,
) -> List[int]:
    """
    Idempotent: s'appuie sur la contrainte 'uniq_event_series_window' +
    ignore_conflicts. Retourne la liste des IDs créés (peut être vide si
    rien de nouveau).

    🔧 Bug fix : `bulk_create` ne déclenche pas `Evenement.save()`. On
    génère donc explicitement le QR code (et tout autre side-effect) AVANT
    l'insertion massive, sinon seules le 1er événement (parent qui passe
    par save()) avait son QR code et toutes les occurrences suivantes
    arrivaient sans QR code en base.
    """
    # Reconstruit en mémoire
    children = parent.build_occurrences()
    if not children:
        return []

    # Cap de sécurité
    if len(children) > max_occurrences:
        logger.info(
            "Capping recurrences for series %s: %d -> %d",
            parent.series_id, len(children), max_occurrences,
        )
        children = children[:max_occurrences]

    # 🔧 Génère le QR code de CHAQUE enfant avant le bulk_create.
    for child in children:
        _ensure_qr_code(child)

    using = parent._state.db or 'default'
    parent_id = parent.pk
    series_id = parent.series_id

    # IDs déjà présents dans la série avant insertion
    existing_ids_before = set(
        Evenement.objects.using(using)
        .filter(series_id=series_id, parent_id=parent_id)
        .values_list('id', flat=True)
    )

    with connections[using].cursor() as cur:
        # 🔒 verrou global pour limiter les courses entre workers Celery
        _pg_advisory_lock(cur, ADVISORY_LOCK_KEY)
        try:
            with transaction.atomic(using=using):
                # On ne définit pas 'code' manuellement : default=eventcode
                # s'applique. ignore_conflicts garantit l'idempotence sur
                # 'uniq_event_series_window'.
                Evenement.objects.using(using).bulk_create(
                    children, ignore_conflicts=True, batch_size=500,
                )
        finally:
            _pg_advisory_unlock(cur, ADVISORY_LOCK_KEY)

    # Diff entre avant et après pour ne renvoyer que les IDs CRÉÉS lors de
    # cet appel (l'ancienne implémentation renvoyait toute la série, ce qui
    # rendait le retour ininterprétable côté appelant).
    after_ids = set(
        Evenement.objects.using(using)
        .filter(series_id=series_id, parent_id=parent_id)
        .values_list('id', flat=True)
    )
    return sorted(after_ids - existing_ids_before)