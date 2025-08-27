# services/events.py
from typing import List
from django.db import transaction, connections
from django.utils import timezone
from event.models import Evenement

ADVISORY_LOCK_KEY = 0xE71E51D  # clé arbitraire globale

def _pg_advisory_lock(cur, key):
    cur.execute("SELECT pg_advisory_lock(%s)", [key])

def _pg_advisory_unlock(cur, key):
    cur.execute("SELECT pg_advisory_unlock(%s)", [key])

def generate_recurrences_for_parent(parent: Evenement, max_occurrences: int = 1000) -> List[int]:
    """
    Idempotent: s'appuie sur la contrainte 'uniq_event_series_window' + ignore_conflicts.
    Retourne la liste des IDs créés (peut être vide si rien de nouveau).
    """
    # Reconstruit en mémoire
    children = parent.build_occurrences()
    if not children:
        return []

    # Cap de sécurité
    if len(children) > max_occurrences:
        children = children[:max_occurrences]

    created_ids = []
    using = parent._state.db or 'default'
    with connections[using].cursor() as cur:
        # 🔒 verrou global simple + clé partagée avec la série pour limiter les courses
        _pg_advisory_lock(cur, ADVISORY_LOCK_KEY)
        try:
            with transaction.atomic(using=using):
                # ⚠️ On ne définit pas 'code' manuellement → default=eventcode s'applique
                # Insertion massive, ignore les doublons (idempotence)
                Evenement.objects.using(using).bulk_create(children, ignore_conflicts=True, batch_size=500)

                # Récupérer les IDs créés (ceux déjà présents ne seront pas retournés)
                created = Evenement.objects.using(using).filter(
                    series_id=parent.series_id,
                    parent=parent
                ).values_list('id', flat=True)
                created_ids = list(created)
        finally:
            _pg_advisory_unlock(cur, ADVISORY_LOCK_KEY)
    return created_ids