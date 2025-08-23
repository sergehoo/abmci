# fidele/services/nearest_church.py
from __future__ import annotations

from typing import Optional
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point

from fidele.models import Fidele, Eglise


def _point_from_fidele(f: Fidele) -> Optional[Point]:
    """
    Essaie d’obtenir un Point WGS84 (lon, lat) depuis le fidèle.
    Adapte selon ton modèle 'Location' (lat/lon, point, etc.).
    """
    loc = getattr(f, "location", None)
    if not loc:
        return None

    # 1) Si Location a déjà un GeoDjango PointField nommé 'point' (SRID 4326)
    pt = getattr(loc, "point", None)
    if pt:
        return pt

    # 2) Si Location stocke des colonnes latitude/longitude (float)
    lat = getattr(loc, "latitude", None)
    lon = getattr(loc, "longitude", None)
    if lat is not None and lon is not None:
        try:
            return Point(float(lon), float(lat), srid=4326)
        except Exception:
            return None

    # 3) Si le fidèle porte directement des coords (ex. f.lat / f.lon)
    lat2 = getattr(f, "lat", None)
    lon2 = getattr(f, "lon", None)
    if lat2 is not None and lon2 is not None:
        try:
            return Point(float(lon2), float(lat2), srid=4326)
        except Exception:
            return None

    return None


def find_nearest_eglise_for_fidele(f: Fidele, *, max_radius_km: float | None = None) -> Optional[Eglise]:
    """
    Retourne l’église la plus proche du fidèle (optionnellement dans un rayon max).
    """
    pt = _point_from_fidele(f)
    if not pt:
        return None

    qs = Eglise.objects.filter(location__isnull=False).annotate(
        distance=Distance("location", pt)
    ).order_by("distance")

    if max_radius_km is None:
        return qs.first()

    # Filtre par rayon si demandé
    max_m = float(max_radius_km) * 1000.0
    qs = qs.filter(distance__lte=max_m)
    return qs.first()


def assign_nearest_eglise_if_missing(f: Fidele, *, max_radius_km: float | None = None) -> bool:
    """
    Si f.eglise est vide, cherche l’église la plus proche et l’affecte.
    Retourne True si mise à jour effectuée, False sinon.
    """
    if f.eglise_id:
        return False

    nearest = find_nearest_eglise_for_fidele(f, max_radius_km=max_radius_km)
    if not nearest:
        return False

    # Mise à jour ciblée pour éviter les boucles de sauvegarde
    type(f).objects.filter(pk=f.pk, eglise__isnull=True).update(eglise=nearest)
    return True
