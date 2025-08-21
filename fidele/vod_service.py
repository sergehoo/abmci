# core/services/vod_from_db.py
from __future__ import annotations

import hashlib
from typing import Optional

from django.utils import timezone
from django.db import transaction

from fidele.models import BibleVersion, BibleVerse, VerseOfDay, Eglise


def _daily_seed(version_code: str, language: str, on_date, eglise_id: int | None) -> int:
    # Si eglise_id est fourni, le verset variera par église (seed différent)
    s = f"{on_date.isoformat()}|{version_code}|{language}|EGLISE:{eglise_id or 'ALL'}"
    h = hashlib.sha1(s.encode('utf-8')).hexdigest()
    return int(h[:8], 16)


def pick_daily_verse_from_db(
    version_code: str = "LSG",
    language: str = "fr",
    *,
    on_date=None,
    eglise: Optional[Eglise] = None,
) -> dict:
    """
    Retourne un dict {date, version, language, text, reference, context_key}.
    - on_date: date utilisée pour le seed (par défaut: today)
    - eglise: si fourni, le seed inclut eglise.id pour varier par église
    """
    on_date = on_date or timezone.localdate()

    # 1) version
    try:
        v = BibleVersion.objects.get(code=version_code)
    except BibleVersion.DoesNotExist:
        v = BibleVersion.objects.order_by('code').first()
        if not v:
            raise RuntimeError("Aucune BibleVersion disponible")

    # 2) total
    total = getattr(v, "total_verses", None) or BibleVerse.objects.filter(version=v).count()
    if total <= 0:
        raise RuntimeError(f"Aucun verset pour la version {v.code}")

    # 3) seed → offset (varie par église si fournie)
    eglise_id = getattr(eglise, "id", None)
    seed = _daily_seed(v.code, language, on_date, eglise_id)
    offset = seed % total

    # 4) fetch
    row = (BibleVerse.objects
           .filter(version=v)
           .order_by('id')
           .values('book', 'chapter', 'verse', 'text')
           [offset:offset+1]
           .first())
    if not row:
        row = (BibleVerse.objects
               .filter(version=v)
               .order_by('id')
               .values('book', 'chapter', 'verse', 'text')
               .first())

    reference = f"{row['book']} {row['chapter']}:{row['verse']}"
    return {
        "date": on_date,
        "version": v.code,
        "language": language,
        "text": row["text"],
        "reference": reference,
        "context_key": "DEFAULT",
    }


def get_or_create_vod_cache(
    *,
    eglise: Eglise,
    version_code: str = "LSG",
    language: str = "fr",
    on_date=None,
) -> VerseOfDay:
    """
    Cache par église (cohérent avec unique_together (date, eglise)).
    Évite des recalculs et historise la sélection.
    """
    on_date = on_date or timezone.localdate()

    obj = VerseOfDay.objects.filter(
        date=on_date, eglise=eglise, version=version_code, language=language
    ).first()
    if obj:
        return obj

    data = pick_daily_verse_from_db(version_code, language, on_date=on_date, eglise=eglise)
    with transaction.atomic():
        obj, _ = VerseOfDay.objects.get_or_create(
            date=data["date"],
            eglise=eglise,
            defaults={
                "version": data["version"],
                "language": data["language"],
                "context_key": data.get("context_key", "DEFAULT"),
                "text": data["text"],
                "reference": data["reference"],
            },
        )
    return obj