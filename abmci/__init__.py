# abmci/__init__.py

# Ne pas importer l'app Celery au chargement de Django pour éviter
# les effets de bords sur runserver/migrations/tests.
# (Celery sera importée par les workers/beat via -A abmci.celery_app:app)
try:
    from .celery_app import app as celery_app  # pragma: no cover
except Exception:
    celery_app = None

__all__ = ("celery_app",)