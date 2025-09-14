# abmci/settings/dev.py
from .base import *
SECRET_KEY = 'django-insecure-+qv9un1&5@8q&yl5*^-jl_iw066p2o%7hdxsom0fqyn1^^cr@x'

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "10.0.2.2"]

# SQLite par défaut (hérité), sinon:
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": "abmci2",
        "USER": "postgres",
        "PASSWORD": "weddingLIFE18",
        "HOST": "localhost",
        "PORT": "5433",
    }
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
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# GDAL_LIBRARY_PATH = os.getenv('GDAL_LIBRARY_PATH', '/opt/homebrew/opt/gdal/lib/libgdal.dylib')
# GEOS_LIBRARY_PATH = os.getenv('GEOS_LIBRARY_PATH', '/opt/homebrew/opt/geos/lib/libgeos_c.dylib')
# Emails en console si tu veux en dev
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
