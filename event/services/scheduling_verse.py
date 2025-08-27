# services/scheduling.py
from __future__ import annotations
from typing import Iterable, Sequence, Dict, List, Tuple, Set
from datetime import timedelta, date
import random

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from fidele.models import Eglise, BibleVerse, VerseOfDay, BibleVersion


def verse_key_from_bibleverse(v: BibleVerse) -> str:
    # clé stable indépendante du libellé texte
    return f"{v.version.code}:{v.book}:{v.chapter}:{v.verse}"


def verse_key_from_vod(vod: VerseOfDay) -> str:
    # quand on n’a que VerseOfDay (version est un code str, reference = "Livre C:V")
    # on normalise légèrement la référence
    ref = " ".join((vod.reference or "").split())  # compacter espaces
    return f"{vod.version}:{ref}"  # ex: "LSG:Psaumes 23:1"


def _daterange(d1: date, d2: date) -> List[date]:
    if d2 < d1: return []
    n = (d2 - d1).days + 1
    return [d1 + timedelta(days=i) for i in range(n)]


def pick_candidate_verses(
    version: BibleVersion,
    language: str,
    keywords: Sequence[str] | None = None,
    books: Sequence[str] | None = None,
    shuffle: bool = True,
) -> List[BibleVerse]:
    qs = BibleVerse.objects.select_related("version").filter(version=version)
    if books:
        books = [b.strip() for b in books if b.strip()]
        if books:
            qs = qs.filter(book__in=books)
    if keywords:
        q = Q()
        for kw in (k.strip() for k in keywords if k.strip()):
            q |= Q(text__icontains=kw) | Q(book__icontains=kw)
        if q:
            qs = qs.filter(q)
    candidates = list(qs)
    if shuffle:
        random.shuffle(candidates)
    return candidates


def _recent_keys_per_eglise(eglise: Eglise, since: date) -> Set[str]:
    """Clés de versets déjà utilisés récemment dans cette église."""
    recent = VerseOfDay.objects.filter(eglise=eglise, date__gte=since).only(
        "version", "reference"
    )
    return {verse_key_from_vod(v) for v in recent}


def schedule_vod_for_period(
    eglises: Iterable[Eglise],
    start: date,
    end: date,
    version: BibleVersion,
    language: str,
    candidates: Sequence[BibleVerse],
    context_key: str = "DEFAULT",
    avoid_recent_days: int = 90,
    overwrite_existing: bool = False,
    unique_per_day_across_eglises: bool = True,
    diversify_seeded_shuffle: bool = True,
) -> Dict[int, int]:
    """
    Programme des VOD en respectant:
      - pas de répétition récente par église (avoid_recent_days),
      - pas le même verset le même jour pour 2 églises (unique_per_day_across_eglises),
      - séquence différente par église (diversify_seeded_shuffle).

    Idempotent grâce à unique_together(date, eglise) + bulk_create(ignore_conflicts=True).
    """
    days = _daterange(start, end)
    if not days or not candidates:
        return {e.id: 0 for e in eglises}

    # Prépare un pool (liste) + un mapping clé->objet pour accès rapide
    pool = list(candidates)
    pool_keys = [verse_key_from_bibleverse(v) for v in pool]

    results: Dict[int, int] = {}
    today = timezone.localdate()
    recent_since = today - timedelta(days=avoid_recent_days or 0)

    # Pour interdire le même verset pour plusieurs églises le même jour
    # dict: date -> set(keys déjà attribuées ce jour)
    day_used: Dict[date, Set[str]] = {d: set() for d in days}

    for e in eglises:
        # mémoire récente par église
        recent_keys = _recent_keys_per_eglise(e, recent_since) if avoid_recent_days else set()

        # on dérive un “offset” de départ pour l’église
        # afin que chaque église parcourt le pool dans un ordre différent.
        # (graine stable = id église + premier jour)
        offset = 0
        if diversify_seeded_shuffle:
            seed = hash((e.id, start.toordinal()))
            # un modulo évite les grands décalages inutiles
            offset = abs(seed) % max(1, len(pool))

        items_to_create: List[VerseOfDay] = []
        index = offset

        for d in days:
            picked = None
            seen = 0
            # essai circulaire sur tout le pool
            while seen < len(pool):
                v = pool[index % len(pool)]
                k = pool_keys[index % len(pool)]
                index += 1
                seen += 1

                # contraintes :
                if k in recent_keys:
                    continue
                if unique_per_day_across_eglises and k in day_used[d]:
                    continue

                picked = v
                break

            # fallback : si tout est “bloqué”, on prend quand même le prochain
            if picked is None:
                picked = pool[index % len(pool)]
                k = pool_keys[index % len(pool)]
                index += 1

            # on marque l’utilisation
            recent_keys.add(k)
            if unique_per_day_across_eglises:
                day_used[d].add(k)

            ref = f"{picked.book} {picked.chapter}:{picked.verse}"
            items_to_create.append(
                VerseOfDay(
                    date=d,
                    eglise=e,
                    version=version.code,
                    language=language,
                    context_key=context_key or "DEFAULT",
                    text=picked.text,
                    reference=ref,
                )
            )

        # Écriture DB
        created = 0
        with transaction.atomic():
            if not overwrite_existing:
                VerseOfDay.objects.bulk_create(
                    items_to_create, ignore_conflicts=True, batch_size=500
                )
                created = VerseOfDay.objects.filter(
                    eglise=e, date__in=days
                ).count()  # estimation grossière
            else:
                # upsert simple: update ceux qui existent, insert le reste
                dates = [x.date for x in items_to_create]
                existing_dates = set(
                    VerseOfDay.objects.filter(eglise=e, date__in=dates).values_list("date", flat=True)
                )
                to_update = [x for x in items_to_create if x.date in existing_dates]
                to_insert = [x for x in items_to_create if x.date not in existing_dates]

                for x in to_update:
                    VerseOfDay.objects.filter(eglise=e, date=x.date).update(
                        text=x.text,
                        reference=x.reference,
                        version=version.code,
                        language=language,
                        context_key=context_key or "DEFAULT",
                    )
                if to_insert:
                    VerseOfDay.objects.bulk_create(to_insert, ignore_conflicts=True, batch_size=500)
                    created = len(to_insert)

        results[e.id] = created

    return results