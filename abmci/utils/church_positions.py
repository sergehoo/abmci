from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D

def calculate_distance(point1, point2):
    """Calculer la distance en kilomètres entre deux points"""
    if point1 and point2:
        # Convertir en radians pour le calcul de distance
        return point1.distance(point2) * 100  # Approximation simplifiée
    return None

def get_eglises_proches(latitude, longitude, radius_km=10):
    """Retourner les églises dans un rayon donné"""
    user_location = Point(longitude, latitude, srid=4326)
    return Eglise.objects.filter(
        location__isnull=False,
        location__distance_lte=(user_location, D(km=radius_km))
    ).annotate(distance=Distance('location', user_location)).order_by('distance')