# abmci/settings/prod.py
from .base import *
DEBUG = True
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",") if os.environ.get("ALLOWED_HOSTS") else []

# Postgres recommandé en prod
DATABASES = {
  "default": {
    "ENGINE": "django.contrib.gis.db.backends.postgis",
    "NAME": os.environ.get("DB_NAME"),
    "USER": os.environ.get("DB_USER"),
    "PASSWORD": os.environ.get("DB_PASSWORD"),
    "HOST": os.environ.get("DB_HOST"),
    "PORT": os.environ.get("DB_PORT", "5432"),
  }
}

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# Static files : éventuellement via WhiteNoise/CDN
# STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

DEBUG = False
SECRET_KEY = os.getenv("SECRET_KEY")  # mets une vraie clé longue

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000         # 1 an
SECURE_HSTS_INCLUDE_SUBDOMAINS = True  # uniquement si tous les sous-domaines sont HTTPS
SECURE_HSTS_PRELOAD = True             # si tu soumets au preload HSTS
