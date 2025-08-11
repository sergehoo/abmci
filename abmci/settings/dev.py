# abmci/settings/dev.py
from .base import *
from decouple import config, Csv

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "10.0.2.2"]

# SQLite par défaut (hérité), sinon:
# DATABASES["default"] = {
#     "ENGINE": "django.db.backends.postgresql",
#     "NAME": config("DB_NAME", default="abmci_dev"),
#     "USER": config("DB_USER", default="postgres"),
#     "PASSWORD": config("DB_PASSWORD", default=""),
#     "HOST": config("DB_HOST", default="localhost"),
#     "PORT": config("DB_PORT", default="5432"),
# }

CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False

CORS_ALLOWED_ORIGINS += [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://10.0.2.2:8000",
]
CSRF_TRUSTED_ORIGINS += [
    "http://127.0.0.1:8000",
    "http://10.0.2.2:8000",
]

# Emails en console si tu veux en dev
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"