# core/services/vod_from_db.py
import hashlib
from django.utils import timezone
from django.db import transaction

from fidele.models import BibleVersion, BibleVerse, VerseOfDay


def _daily_seed(version_code: str, language: str, on_date) -> int:
    s = f"{on_date.isoformat()}|{version_code}|{language}"
    h = hashlib.sha1(s.encode('utf-8')).hexdigest()
    # Convertit les 8 premiers hex en entier
    return int(h[:8], 16)

def pick_daily_verse_from_db(version_code="LSG", language="fr"):
    """
    Retourne un dict {text, reference, version, language, date}.
    La sélection est déterministe pour une date donnée.
    """
    today = timezone.localdate()
    # 1) version
    try:
        v = BibleVersion.objects.get(code=version_code)
        # (si tu gères la langue au niveau version, adapte le filtre)
    except BibleVersion.DoesNotExist:
        # fallback: première version dispo
        v = BibleVersion.objects.order_by('code').first()
        if not v:
            raise RuntimeError("Aucune BibleVersion disponible")

    # 2) total
    total = v.total_verses or BibleVerse.objects.filter(version=v).count()
    if total <= 0:
        raise RuntimeError(f"Aucun verset pour la version {v.code}")

    # 3) seed → offset
    seed = _daily_seed(v.code, language, today)
    offset = seed % total

    # 4) fetch via OFFSET (rapide si table pas énorme; PK est indexée)
    row = (BibleVerse.objects
           .filter(version=v)
           .order_by('id')
           .values('book', 'chapter', 'verse', 'text')
           [offset:offset+1]
           .first())
    if not row:
        # ultra-rare (concurrence) → retombe sur le premier
        row = (BibleVerse.objects
               .filter(version=v)
               .order_by('id')
               .values('book', 'chapter', 'verse', 'text')
               .first())

    reference = f"{row['book']} {row['chapter']}:{row['verse']}"
    return {
        "date": today,
        "version": v.code,
        "language": language,
        "text": row["text"],
        "reference": reference,
    }

def get_or_create_vod_cache(version_code="LSG", language="fr"):
    """
    Utilise VerseOfDay comme cache (1 seule écriture/jour).
    """
    today = timezone.localdate()
    obj = VerseOfDay.objects.filter(date=today, version=version_code, language=language).first()
    if obj:
        return obj

    data = pick_daily_verse_from_db(version_code, language)
    with transaction.atomic():
        obj, _ = VerseOfDay.objects.get_or_create(
            date=data["date"], version=data["version"], language=data["language"],
            defaults={"text": data["text"], "reference": data["reference"]}
        )
    return obj