# abmci/settings/dev.py
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "10.0.2.2"]

# SQLite par défaut (hérité), sinon:
DATABASES["default"] = {
    "ENGINE": "django.contrib.gis.db.backends.postgis",
    "NAME": os.environ.get("DB_NAME"),
    "USER": os.environ.get("DB_USER"),
    "PASSWORD": os.environ.get("DB_PASSWORD"),
    "HOST": os.environ.get("DB_HOST"),
    "PORT": os.environ.get("DB_PORT", default="5432"),
}

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

# GDAL_LIBRARY_PATH = os.getenv('GDAL_LIBRARY_PATH', '/opt/homebrew/opt/gdal/lib/libgdal.dylib')
# GEOS_LIBRARY_PATH = os.getenv('GEOS_LIBRARY_PATH', '/opt/homebrew/opt/geos/lib/libgeos_c.dylib')
# Emails en console si tu veux en dev
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"