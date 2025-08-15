# abmci/notifications/fcm.py
from __future__ import annotations
import os
import json
import base64
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings

def _build_credential():
    """
    Construit un credentials.Credential depuis:
    - settings.FIREBASE_SERVICE_ACCOUNT_PATH
    - settings.FIREBASE_CREDENTIALS_JSON (dict)
    - settings.FIREBASE_SERVICE_ACCOUNT_B64 (base64 JSON)
    - GOOGLE_APPLICATION_CREDENTIALS (ADC)
    Retourne None si ADC doit être utilisé sans args.
    """
    path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_PATH", None)
    creds_dict = getattr(settings, "FIREBASE_CREDENTIALS_JSON", None)
    b64 = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_B64", None) or os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
    adc = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or getattr(settings, "USE_GOOGLE_APPLICATION_DEFAULT", None)

    if path:
        return credentials.Certificate(path)

    if creds_dict:
        return credentials.Certificate(creds_dict)

    if b64:
        try:
            data = json.loads(base64.b64decode(b64).decode("utf-8"))
            return credentials.Certificate(data)
        except Exception as e:
            raise ValueError(f"FIREBASE_SERVICE_ACCOUNT_B64 invalide: {e}")

    if adc:
        # Application Default Credentials; nécessite la variable GOOGLE_APPLICATION_CREDENTIALS
        return credentials.ApplicationDefault()

    # Rien fourni → on laisse firebase_admin.initialize_app() sans credentials
    # (échouera si aucune ADC dispo). Mieux vaut lever une erreur explicite :
    return None

def _ensure_initialized():
    """Initialise l'app Firebase une seule fois, proprement."""
    if firebase_admin._apps:
        return
    cred = _build_credential()
    if cred is not None:
        firebase_admin.initialize_app(cred)
    else:
        # Donne un message explicite au lieu d'un None cryptique
        raise RuntimeError(
            "Firebase non configuré. "
            "Renseigne FIREBASE_SERVICE_ACCOUNT_PATH, FIREBASE_CREDENTIALS_JSON, "
            "FIREBASE_SERVICE_ACCOUNT_B64 ou GOOGLE_APPLICATION_CREDENTIALS."
        )

def send_to_token(token: str, title: str, body: str, data: dict | None = None):
    _ensure_initialized()
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in (data or {}).items()},
        token=token,
    )
    return messaging.send(message)

def send_to_topic(topic: str, title: str, body: str, data: dict | None = None):
    _ensure_initialized()
    # FCM demande un topic "nettoyé" (lettres, chiffres, _-)
    norm = topic.strip().replace(" ", "_")
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in (data or {}).items()},
        topic=norm,
    )
    return messaging.send(message)