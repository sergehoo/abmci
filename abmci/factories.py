"""Données minimales partagées par les tests (pas de dépendance externe)."""
from django.contrib.auth import get_user_model

from fidele.models import Eglise, Fidele, Location

User = get_user_model()


def ensure_reference_data():
    # Fidele.location est non nullable avec default=1 : la Location pk=1 doit exister
    Location.objects.get_or_create(pk=1, defaults={"name": "Abidjan", "type": None})


def make_user(username, *, email=None, staff=False, superuser=False, password="Motdepasse-test-1"):
    ensure_reference_data()
    if superuser:
        user = User.objects.create_superuser(username=username, email=email or f"{username}@example.com",
                                             password=password)
    else:
        user = User.objects.create_user(username=username, email=email or f"{username}@example.com",
                                        password=password, is_staff=staff)
    return user


def fidele_of(user):
    # Créée par le signal post_save create_fidele
    return Fidele.objects.get(user=user)


def make_eglise(name="Église test"):
    return Eglise.objects.create(name=name)
