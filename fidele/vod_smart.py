# core/services/vod_smart.py
import hashlib
from datetime import date, timedelta, datetime
from typing import Iterable, Optional, Tuple
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from event.models import Evenement
from fidele.models import BibleVersion, BibleVerse, Eglise, VerseOfDay


# ---------- helpers seed/offset ----------
def _seed_int(s: str) -> int:
    h = hashlib.sha1(s.encode('utf-8')).hexdigest()
    return int(h[:8], 16)


def _deterministic_pick(qs, context_key: str, version_code: str, language: str, on_date: date, eglise_id: int,
                        exclude_ids: Optional[Iterable[int]] = None) -> Optional['BibleVerse']:
    """
    Pick déterministe via seed + offset, avec exclu optionnelle d'IDs (éviter répétitions).
    """
    if exclude_ids:
        qs = qs.exclude(id__in=set(exclude_ids))
    total = qs.count()
    if total == 0:
        return None
    seed = _seed_int(f"{on_date.isoformat()}|{version_code}|{language}|{context_key}|EGLISE:{eglise_id}")
    offset = seed % total
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
                    keywords: Optional[Iterable[str]] = None,
                    min_len: int = 40, max_len: int = 240):
    """
    Contraintes simples de longueur pour lisibilité sur mobile + filtres livres/mots-clés.
    """
    qs = BibleVerse.objects.filter(version=version)
    if books:
        qs = qs.filter(book__in=list(set(books)))
    if keywords:
        q = Q()
        for k in keywords:
            q |= Q(text__icontains=k)
        qs = qs.filter(q)
    # longueur (SQL simple via LENGTH)
    qs = qs.extra(where=["length(text) BETWEEN %s AND %s"], params=[min_len, max_len])
    return qs


def _recent_usage_ids(eglise: Eglise, window_days: int = 90) -> Iterable[int]:
    """
    IDs des versets (BibleVerse.id) récemment utilisés par cette église.
    On mappe book/chapter/verse à leurs IDs via une requête.
    """
    since = timezone.localdate() - timedelta(days=window_days)
    usages = VerseUsage.objects.filter(eglise=eglise, used_on__gte=since) \
        .values('book', 'chapter', 'verse')
    if not usages:
        return []

    # Récupère les IDs correspondants (tous versions confondues pour le livre/ch/verset)
    clauses = Q()
    for u in usages:
        clauses |= Q(book=u['book'], chapter=u['chapter'], verse=u['verse'])
    if not clauses.children:
        return []

    return (BibleVerse.objects.filter(clauses)
            .values_list('id', flat=True))


def _save_vod_and_usage(eglise: Eglise, on_date: date, version: BibleVersion,
                        text: str, book: str, chapter: int, verse: int,
                        language: str, context_key: str, reference: str):
    with transaction.atomic():
        # Un VOD par (date, eglise)
        VerseOfDay.objects.update_or_create(
            date=on_date, eglise=eglise,
            defaults={
                'version': version.code,
                'language': language,
                'context_key': context_key,
                'text': text,
                'reference': reference,
            }
        )
        # Historiser l’usage pour l’anti-répétition
        VerseUsage.objects.create(
            eglise=eglise,
            used_on=on_date,
            version=version.code,
            book=book,
            chapter=chapter,
            verse=verse,
        )


# ---------- Sélection principale ----------
def pick_smart_daily_verse_for_eglise(
        eglise: Eglise,
        version_code: str = "LSG",
        language: str = "fr",
        on_date: Optional[date] = None,
) -> Tuple[date, str, str, str, str, str]:
    """
    Retourne (date, version_code, language, context_key, text, reference)
    Choix par priorité: événements (±7j) > saison > jour de semaine > fallback.
    Variation déterministe par église (seed inclut l’ID).
    Anti-répétition (fenêtre 90 jours).
    """
    if not eglise:
        raise ValueError("Église requise")

    on_date = on_date or timezone.localdate()

    # Version par défaut / ou préférée si ton modèle Eglise en stocke une
    try:
        version = BibleVersion.objects.get(code=version_code)
    except BibleVersion.DoesNotExist:
        version = BibleVersion.objects.order_by('code').first()
        if not version:
            raise RuntimeError("Aucune BibleVersion disponible")

    # 0) si déjà caché pour aujourd’hui → renvoyer direct
    cached = VerseOfDay.objects.filter(date=on_date, eglise=eglise).first()
    if cached:
        return (cached.date, cached.version, cached.language, cached.context_key, cached.text, cached.reference)

    # IDs à exclure (anti-répétition)
    exclude_ids = list(_recent_usage_ids(eglise, window_days=90))

    # ----- 1) événements à ±7 jours (priorité) -----
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
                books = THEME_KEYWORDS[tag].get("books")
                keywords = THEME_KEYWORDS[tag].get("keywords")
                qs = _build_queryset(version, books, keywords)
                chosen = _deterministic_pick(qs, ctx, version.code, language, on_date, eglise.id, exclude_ids)
                if chosen:
                    ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
                    _save_vod_and_usage(
                        eglise, on_date, version, chosen.text,
                        chosen.book, chosen.chapter, chosen.verse,
                        language, ctx, ref
                    )
                    return (on_date, version.code, language, ctx, chosen.text, ref)

    # ----- 2) saison/fête -----
    season = _season_for(on_date)
    if season and season in SEASON_BOOK_POOLS:
        ctx = f"SEASON:{season}"
        qs = _build_queryset(version, books=SEASON_BOOK_POOLS[season])
        chosen = _deterministic_pick(qs, ctx, version.code, language, on_date, eglise.id, exclude_ids)
        if chosen:
            ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
            _save_vod_and_usage(
                eglise, on_date, version, chosen.text,
                chosen.book, chosen.chapter, chosen.verse,
                language, ctx, ref
            )
            return (on_date, version.code, language, ctx, chosen.text, ref)

    # ----- 3) jour de la semaine -----
    weekday = on_date.weekday()  # 0=lundi … 6=dimanche
    ctx = f"WEEKDAY:{weekday}"
    qs = _build_queryset(version, books=WEEKDAY_POOLS.get(weekday))
    chosen = _deterministic_pick(qs, ctx, version.code, language, on_date, eglise.id, exclude_ids)
    if chosen:
        ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
        _save_vod_and_usage(
            eglise, on_date, version, chosen.text,
            chosen.book, chosen.chapter, chosen.verse,
            language, ctx, ref
        )
        return (on_date, version.code, language, ctx, chosen.text, ref)

    # ----- 4) fallback -----
    ctx = "DEFAULT"
    qs = _build_queryset(version)
    chosen = _deterministic_pick(qs, ctx, version.code, language, on_date, eglise.id, exclude_ids)
    if not chosen:
        raise RuntimeError("Aucun verset disponible")
    ref = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
    _save_vod_and_usage(
        eglise, on_date, version, chosen.text,
        chosen.book, chosen.chapter, chosen.verse,
        language, ctx, ref
    )
    return (on_date, version.code, language, ctx, chosen.text, ref)
