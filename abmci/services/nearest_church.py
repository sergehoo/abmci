from __future__ import annotations
from typing import Optional

from django.utils import timezone
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance

from fidele.models import Fidele, Eglise, FidelePosition


# -------------------------------
# Sélection d'un Point WGS84
# -------------------------------

def _point_from_position(pos: FidelePosition) -> Optional[Point]:
    try:
        return Point(float(pos.longitude), float(pos.latitude), srid=4326)
    except Exception:
        return None


def _latest_valid_position(
    f: Fidele,
    *,
    max_age_hours: int | None = 48,
    max_accuracy_m: float | None = 500.0,
) -> Optional[FidelePosition]:
    """
    Récupère la DERNIÈRE position du fidèle,
    en appliquant (optionnel) un filtre de fraîcheur et de précision.
    """
    qs = FidelePosition.objects.filter(fidele=f).order_by("-captured_at")

    pos = qs.first()
    if not pos:
        return None

    # Fraîcheur max
    if max_age_hours is not None:
        age = timezone.now() - pos.captured_at
        if age.total_seconds() > max_age_hours * 3600:
            return None

    # Précision max
    if max_accuracy_m is not None and pos.accuracy is not None:
        try:
            if float(pos.accuracy) > float(max_accuracy_m):
                return None
        except Exception:
            pass

    return pos


def _point_from_fidele_or_location(f: Fidele) -> Optional[Point]:
    """
    Fallback si pas de FidelePosition exploitable:
    essaie de déduire un Point depuis le modèle Location associé.
    Adapte selon ton modèle Location (lat/lon ou PointField).
    """
    loc = getattr(f, "location", None)
    if not loc:
        return None

    # 1) Si Location fournit un point GeoDjango directement (SRID=4326)
    pt = getattr(loc, "point", None)
    if pt:
        return pt

    # 2) Si Location stocke latitude/longitude en colonnes
    lat = getattr(loc, "latitude", None)
    lon = getattr(loc, "longitude", None)
    if lat is not None and lon is not None:
        try:
            return Point(float(lon), float(lat), srid=4326)
        except Exception:
            return None

    # 3) Si Fidele porte des coords (rare)
    lat2 = getattr(f, "lat", None)
    lon2 = getattr(f, "lon", None)
    if lat2 is not None and lon2 is not None:
        try:
            return Point(float(lon2), float(lat2), srid=4326)
        except Exception:
            return None

    return None


def _point_for_fidele(
    f: Fidele,
    *,
    max_age_hours: int | None = 48,
    max_accuracy_m: float | None = 500.0,
) -> Optional[Point]:
    """
    Point prioritaire: dernière FidelePosition valide.
    Sinon, fallback sur Location / autres champs.
    """
    pos = _latest_valid_position(f, max_age_hours=max_age_hours, max_accuracy_m=max_accuracy_m)
    if pos:
        pt = _point_from_position(pos)
        if pt:
            return pt
    return _point_from_fidele_or_location(f)


# -------------------------------
# Recherche de l'église la plus proche
# -------------------------------

def find_nearest_eglise_for_fidele(
    f: Fidele,
    *,
    max_radius_km: float | None = None,
    max_age_hours: int | None = 48,
    max_accuracy_m: float | None = 500.0,
) -> Optional[Eglise]:
    """
    Retourne l’église la plus proche d’un fidèle sur la base de sa **dernière position**,
    avec (optionnellement) des contraintes de fraîcheur et de précision.
    """
    pt = _point_for_fidele(f, max_age_hours=max_age_hours, max_accuracy_m=max_accuracy_m)
    if not pt:
        return None

    qs = (
        Eglise.objects.filter(location__isnull=False)
        .annotate(distance=Distance("location", pt))
        .order_by("distance")
    )

    if max_radius_km is None:
        return qs.first()

    max_m = float(max_radius_km) * 1000.0
    return qs.filter(distance__lte=max_m).first()


def assign_nearest_eglise_if_missing(
    f: Fidele,
    *,
    max_radius_km: float | None = None,
    max_age_hours: int | None = 48,
    max_accuracy_m: float | None = 500.0,
) -> bool:
    """
    Si `f.eglise` est vide : cherche la plus proche et l’affecte.
    Retourne True si mise à jour effectuée, False sinon.
    """
    if f.eglise_id:
        return False

    nearest = find_nearest_eglise_for_fidele(
        f,
        max_radius_km=max_radius_km,
        max_age_hours=max_age_hours,
        max_accuracy_m=max_accuracy_m,
    )
    if not nearest:
        return False

    type(f).objects.filter(pk=f.pk, eglise__isnull=True).update(eglise=nearest)
    return True