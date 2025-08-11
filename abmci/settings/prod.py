# abmci/settings/prod.py
from .base import *
from decouple import config, Csv
DEBUG = False
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv(), default=["abmci.com", "www.abmci.com"])

# Postgres recommandé en prod
DATABASES["default"] = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": config("DB_NAME"),
    "USER": config("DB_USER"),
    "PASSWORD": config("DB_PASSWORD"),
    "HOST": config("DB_HOST"),
    "PORT": config("DB_PORT", default="5432"),
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