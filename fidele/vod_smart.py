# core/services/vod_smart.py
import hashlib
from datetime import date, timedelta, datetime
from typing import Iterable, Optional
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from event.models import Evenement
from fidele.models import BibleVersion, BibleVerse, Eglise, VerseOfDay


# ---------- helpers seed/offset ----------
def _seed_int(s: str) -> int:
    h = hashlib.sha1(s.encode('utf-8')).hexdigest()
    return int(h[:8], 16)


def _deterministic_pick(qs, context_key: str, version_code: str, language: str, on_date):
    total = qs.count()
    if total == 0:
        return None
    seed = _seed_int(f"{on_date.isoformat()}|{version_code}|{language}|{context_key}")
    offset = seed % total
    # ordre stable
    return qs.order_by('id')[offset:offset + 1].first()


# ---------- Règles de contexte ----------
SEASON_BOOK_POOLS = {
    "ADVENT": ["Ésaïe", "Luc", "Matthieu", "Psaumes"],
    "CHRISTMAS": ["Luc", "Matthieu", "Ésaïe", "Jean", "Psaumes"],
    "LENT": ["Psaumes", "Ésaïe", "Matthieu", "Marc", "Luc"],
    "EASTER": ["Jean", "Luc", "Matthieu", "Actes", "1 Corinthiens", "Psaumes"],
    "PENTECOST": ["Actes", "Jean", "Romains", "Galates"],
}

WEEKDAY_POOLS = {
    0: ["Proverbes"],  # Lundi
    1: ["Proverbes", "Jacques"],  # Mardi
    2: ["Proverbes", "Romains"],  # Mercredi
    3: ["Proverbes", "Éphésiens"],  # Jeudi
    4: ["Proverbes", "Philippiens", "Colossiens"],  # Vendredi
    5: ["Psaumes", "Marc"],  # Samedi
    6: ["Psaumes", "Jean", "Actes"],  # Dimanche
}

# Thèmes -> critères simples (keywords et/ou livres conseillés)
THEME_KEYWORDS = {
    "mariage": {"keywords": ["amour", "époux", "épouse", "union"],
                "books": ["1 Corinthiens", "Genèse", "Cantique des Cantiques", "Éphésiens"]},
    "bapteme": {"keywords": ["baptême", "baptiser", "eau", "repentance"], "books": ["Actes", "Matthieu", "Marc"]},
    "jeunesse": {"keywords": ["jeune", "enfant", "jeunesse", "instruction"], "books": ["Proverbes", "1 Timothée"]},
    "deuil": {"keywords": ["consolation", "espérance", "larmes", "mort", "résurrection"],
              "books": ["Psaumes", "1 Thessaloniciens", "Jean", "Apocalypse"]},
    "mission": {"keywords": ["mission", "envoyer", "évangile", "nations"], "books": ["Matthieu", "Actes", "Romains"]},
}


def _season_for(d: date) -> Optional[str]:
    y = d.year
    # Périodes approximatives (tu peux raffiner selon calendrier liturgique réel)
    advent_start = date(y, 12, 1)
    christmas_end = date(y, 1, 7)
    lent_start = date(y, 2, 15)
    lent_end = date(y, 3, 31)
    easter_start = date(y, 3, 31)
    easter_end = date(y, 4, 30)
    pentecost = date(y, 5, 19)

    if d >= advent_start or d <= date(y, 1, 6):
        return "ADVENT" if d >= advent_start else "CHRISTMAS"
    if lent_start <= d <= lent_end:
        return "LENT"
    if easter_start <= d <= easter_end:
        return "EASTER"
    if d == pentecost:
        return "PENTECOST"
    return None


def _build_queryset(version: BibleVersion, books: Optional[Iterable[str]] = None,
                    keywords: Optional[Iterable[str]] = None):
    qs = BibleVerse.objects.filter(version=version)
    if books:
        qs = qs.filter(book__in=list(set(books)))
    if keywords:
        q = Q()
        for k in keywords:
            q |= Q(text__icontains=k)
        qs = qs.filter(q)
    return qs


# ---------- Sélection principale ----------
def pick_smart_daily_verse(
        version_code: str = "LSG",
        language: str = "fr",
        on_date: Optional[date] = None,
        eglise: Optional[Eglise] = None,
):
    """
    Choisit un verset en fonction du contexte: événement proche > saison > jour de semaine > fallback.
    Retourne dict {date, version, language, context_key, text, reference}.
    """
    on_date = on_date or timezone.localdate()
    try:
        version = BibleVersion.objects.get(code=version_code)
    except BibleVersion.DoesNotExist:
        version = BibleVersion.objects.order_by('code').first()
        if not version:
            raise RuntimeError("Aucune BibleVersion disponible")

    # 0) événements à ±7 jours (priorité)
    if eglise:
        start = timezone.make_aware(datetime.combine(on_date - timedelta(days=7), datetime.min.time()))
        end = timezone.make_aware(datetime.combine(on_date + timedelta(days=1), datetime.min.time()))
        events = (Evenement.objects
                  .filter(eglise=eglise, date_debut__gte=start, date_fin__lt=end)
                  .order_by('date_debut')[:3])
        for ev in events:
            for tag in (ev.tags or []):
                tag = str(tag).lower().strip()
                if tag in THEME_KEYWORDS:
                    ctx = f"EVENT:{tag}"
                    # cache
                    cached = VerseOfDay.objects.filter(date=on_date, version=version.code, language=language,
                                                       context_key=ctx).first()
                    if cached:
                        return {
                            "date": cached.date,
                            "version": cached.version,
                            "language": cached.language,
                            "context_key": cached.context_key,
                            "text": cached.text,
                            "reference": cached.reference,
                        }
                    conf = THEME_KEYWORDS[tag]
                    qs = _build_queryset(version, conf.get("books"), conf.get("keywords"))
                    chosen = _deterministic_pick(qs, ctx, version.code, language, on_date)
                    if chosen:
                        ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
                        with transaction.atomic():
                            vod, _ = VerseOfDay.objects.get_or_create(
                                date=on_date, version=version.code, language=language, context_key=ctx,
                                defaults={"text": chosen.text, "reference": ref},
                            )
                        return {
                            "date": on_date, "version": version.code, "language": language,
                            "context_key": ctx, "text": chosen.text, "reference": ref,
                        }

    # 1) saison/fête
    season = _season_for(on_date)
    if season and season in SEASON_BOOK_POOLS:
        ctx = f"SEASON:{season}"
        cached = VerseOfDay.objects.filter(date=on_date, version=version.code, language=language,
                                           context_key=ctx).first()
        if cached:
            return {
                "date": cached.date, "version": cached.version, "language": cached.language,
                "context_key": cached.context_key, "text": cached.text, "reference": cached.reference,
            }
        books = SEASON_BOOK_POOLS[season]
        qs = _build_queryset(version, books=books)
        chosen = _deterministic_pick(qs, ctx, version.code, language, on_date)
        if chosen:
            ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
            with transaction.atomic():
                VerseOfDay.objects.get_or_create(
                    date=on_date, version=version.code, language=language, context_key=ctx,
                    defaults={"text": chosen.text, "reference": ref},
                )
            return {
                "date": on_date, "version": version.code, "language": language,
                "context_key": ctx, "text": chosen.text, "reference": ref,
            }

    # 2) jour de la semaine
    weekday = on_date.weekday()  # 0=lundi … 6=dimanche
    ctx = f"WEEKDAY:{weekday}"
    cached = VerseOfDay.objects.filter(date=on_date, version=version.code, language=language, context_key=ctx).first()
    if cached:
        return {
            "date": cached.date, "version": cached.version, "language": cached.language,
            "context_key": cached.context_key, "text": cached.text, "reference": cached.reference,
        }
    books = WEEKDAY_POOLS.get(weekday)
    qs = _build_queryset(version, books=books)
    chosen = _deterministic_pick(qs, ctx, version.code, language, on_date)
    if chosen:
        ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
        with transaction.atomic():
            VerseOfDay.objects.get_or_create(
                date=on_date, version=version.code, language=language, context_key=ctx,
                defaults={"text": chosen.text, "reference": ref},
            )
        return {
            "date": on_date, "version": version.code, "language": language,
            "context_key": ctx, "text": chosen.text, "reference": ref,
        }

    # 3) fallback : tous versets de la version
    ctx = "DEFAULT"
    cached = VerseOfDay.objects.filter(date=on_date, version=version.code, language=language, context_key=ctx).first()
    if cached:
        return {
            "date": cached.date, "version": cached.version, "language": cached.language,
            "context_key": cached.context_key, "text": cached.text, "reference": cached.reference,
        }
    qs = _build_queryset(version)
    chosen = _deterministic_pick(qs, ctx, version.code, language, on_date)
    if not chosen:
        raise RuntimeError("Aucun verset disponible")
    ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
    with transaction.atomic():
        VerseOfDay.objects.get_or_create(
            date=on_date, version=version.code, language=language, context_key=ctx,
            defaults={"text": chosen.text, "reference": ref},
        )
    return {
        "date": on_date, "version": version.code, "language": language,
        "context_key": ctx, "text": chosen.text, "reference": ref,
    }
