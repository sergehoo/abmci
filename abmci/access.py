"""
Contrôle d'accès du back-office web.

Les comptes créés depuis l'app mobile ou l'inscription publique (allauth) ne sont pas staff :
ils peuvent se connecter (suppression de compte, profil) mais n'accèdent pas aux pages de gestion.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


def is_backoffice_user(user) -> bool:
    # Superuser accepté même sans is_staff (comptes promus via shell/SQL sans cocher « statut équipe »)
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Anonyme → redirection vers la connexion ; connecté non staff → 403."""

    def test_func(self):
        return is_backoffice_user(self.request.user)


def staff_required(view_func):
    """Équivalent de StaffRequiredMixin pour les vues fonctions."""

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_backoffice_user(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped
