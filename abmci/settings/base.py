# abmci/settings/base.py
import json
import os
import re
from pathlib import Path
from datetime import timedelta
import firebase_admin
from firebase_admin import credentials

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default

def _split_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]

def _with_scheme(origin: str) -> str:
    # si déjà un schéma → OK
    if origin.startswith(("http://", "https://")):
        return origin
    # localhost + IP → http par défaut (dev)
    if origin in ("localhost",) or re.match(r"^\d{1,3}(\.\d{1,3}){3}$", origin):
        return f"http://{origin}"
    # par défaut pour un domaine → https
    return f"https://{origin}"


# SECRET_KEY = os.environ.get("SECRET_KEY")
SECRET_KEY = 'django-insecure-+qv9un1&5@8q&yl5*^-jl_iw066p2o%7hdxsom0fqyn1^^cr@x'

DEBUG = os.environ.get("DEBUG")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",") if os.environ.get("ALLOWED_HOSTS") else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.gis",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.humanize",
    "simple_history",
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "dj_rest_auth",
    "dj_rest_auth.registration",
    'django_filters',
    "corsheaders",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "qr_code",
    "eden",
    "event",
    "recurrence",
    "fidele",
    "crispy_forms",
    "crispy_bootstrap4",
    "notifications",
    "channels",
    "django_select2",
    "django_countries",
    "phonenumber_field",
    "drf_yasg",
    'celery',
    "django_celery_beat",  # optionnel mais recommandé

]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
# SITE_ID = int(os.environ.get("SITE_ID", 1))
SITE_ID = 1

ROOT_URLCONF = "abmci.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.debug",
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
            "fidele.context_processors.departement_processor",
        ],
    },
}]

WSGI_APPLICATION = "abmci.wsgi.application"
ASGI_APPLICATION = "abmci.asgi.application"

# DB: par défaut sqlite (override en prod)
DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DB_ENGINE", default="django.db.backends.sqlite3"),
        "NAME": os.environ.get("DB_NAME", default=str(BASE_DIR / "db.sqlite3")),
        "USER": os.environ.get("DB_USER", default=""),
        "PASSWORD": os.environ.get("DB_PASSWORD", default=""),
        "HOST": os.environ.get("DB_HOST", default=""),
        "PORT": os.environ.get("DB_PORT", default=""),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-FR"
TIME_ZONE = "Africa/Abidjan"
USE_I18N = True
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.BasicAuthentication",
        # "rest_framework.authentication.SessionAuthentication",
        "dj_rest_auth.jwt_auth.JWTCookieAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,

}
REST_AUTH = {
    "USE_JWT": True,
    "JWT_AUTH_COOKIE": None,  # pas de cookie JWT en mobile
    "JWT_AUTH_REFRESH_COOKIE": None,
    "USER_DETAILS_SERIALIZER": "api.serializers.CustomUserDetailsSerializer",
    'REGISTER_SERIALIZER': 'api.serializers.CustomRegisterSerializer',

}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MIN", 60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOW_CREDENTIALS = True


# ALLOWED_HOSTS: pas de schéma ici !
# ALLOWED_HOSTS = _split_csv_env("ALLOWED_HOSTS")
# ex .env : ALLOWED_HOSTS=administration.abmci.com,abmci.com,127.0.0.1,localhost

# CORS/CSRF: schéma requis
CORS_ALLOWED_ORIGINS = [_with_scheme(o) for o in _split_csv_env("CORS_ALLOWED_ORIGINS")]
CSRF_TRUSTED_ORIGINS = [_with_scheme(o) for o in _split_csv_env("CSRF_TRUSTED_ORIGINS")]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

SITE_ORIGIN = "https://administration.abmci.com"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", default="")
EMAIL_PORT = os.environ.get("EMAIL_PORT")
# EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS")
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", default="")

# Django expects SECONDS (ints), not timedelta:
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 60 * 60 * 24 * 30)  # 30 days
CSRF_COOKIE_AGE = env_int("CSRF_COOKIE_AGE", 60 * 60 * 24 * 7)  # 7 days

# Password reset (Django expects seconds)
PASSWORD_RESET_TIMEOUT = env_int("PASSWORD_RESET_TIMEOUT", 60 * 60 * 24 * 3)  # 3 days

# Security (ints, not timedeltas)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)  # 1 year

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
ACCOUNT_FORMS = {
    "signup": "fidele.form.FideleSignupForm",
    "login": "fidele.form.FideleLoginForm",
}

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "account_login"


ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
# ACCOUNT_EMAIL_VERIFICATION = "mandatory"  # ou "optional"
ACCOUNT_UNIQUE_EMAIL = True

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap4"
CRISPY_TEMPLATE_PACK = "bootstrap4"

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE")
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE")

# ====== ORANGE SMS ======
ORANGE_TOKEN_URL = os.environ.get("ORANGE_TOKEN_URL", default="https://api.orange.com/oauth/v3/token")
ORANGE_SMS_URL = os.environ.get("ORANGE_SMS_URL", default="https://api.orange.com/smsmessaging/v1/outbound/{}/requests")
ORANGE_SMS_CLIENT_ID = os.environ.get("ORANGE_SMS_CLIENT_ID", default="")
ORANGE_SMS_CLIENT_SECRET = os.environ.get("ORANGE_SMS_CLIENT_SECRET", default="")
ORANGE_SMS_SENDER = os.environ.get("ORANGE_SMS_SENDER", default="")  # ex: tel:+225734201

# ====== META WhatsApp Cloud API ======
META_WA_API_VERSION = os.environ.get("META_WA_API_VERSION", default="v20.0")
META_WA_BASE_URL = os.environ.get("META_WA_BASE_URL", default="https://graph.facebook.com")
META_WA_PHONE_NUMBER_ID = os.environ.get("META_WA_PHONE_NUMBER_ID", default="")
META_WA_ACCESS_TOKEN = os.environ.get("META_WA_ACCESS_TOKEN", default="")

# Logging minimal (override prod)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}


CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://abmciredis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://abmciredis:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')
# settings.py
PAYSTACK_PUBLIC_KEY = 'pk_live_xxx'
PAYSTACK_BASE_URL = 'https://api.paystack.co'
PAYSTACK_CURRENCY = 'XOF'  # vérifie la devise Paystack supportée pour ton compte/pays
PAYSTACK_CALLBACK_URL = 'https://administration.abmci.com/payments/callback/'
# Option A — chemin vers le fichier de service account (recommandé en local/Docker)
# FIREBASE_SERVICE_ACCOUNT_PATH = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")  # ex: /run/secrets/firebase.json

# Option B — contenu JSON du service account en variable d'env (recommandé en prod PaaS)
_FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
FIREBASE_SERVICE_ACCOUNT_DICT = json.loads(_FIREBASE_SERVICE_ACCOUNT_JSON) if _FIREBASE_SERVICE_ACCOUNT_JSON else None

if FIREBASE_SERVICE_ACCOUNT_DICT and not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_DICT)
    firebase_admin.initialize_app(cred)