# abmci/settings/prod.py
from .base import *
SECRET_KEY = os.environ.get("SECRET_KEY")
DEBUG = True
ALLOWED_HOSTS = ["localhost","administration.abmci.com", "127.0.0.1", "10.0.2.2"]

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


SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000         # 1 an
SECURE_HSTS_INCLUDE_SUBDOMAINS = True  # uniquement si tous les sous-domaines sont HTTPS
SECURE_HSTS_PRELOAD = True             # si tu soumets au preload HSTS

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://abmciredis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://abmciredis:6379/0")

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE