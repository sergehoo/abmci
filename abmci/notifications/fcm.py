# # abmci/notifications/fcm.py
# abmci/notifications/fcm.py
from __future__ import annotations
import os
import re
import json
import base64
import time
from datetime import timedelta
from typing import Iterable, List, Optional, Tuple, Dict

import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings

# -----------------------------
# Credentials & initialization
# -----------------------------

# abmci/notifications/fcm.py (remplace TOUTE la fonction _build_credential et le RuntimeError)


def _build_credential() -> Optional[credentials.Base]:
    from django.conf import settings

    path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_PATH", None)
    if path:
        return credentials.Certificate(path)

    dict_cfg = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_DICT", None)
    if isinstance(dict_cfg, dict) and dict_cfg:
        return credentials.Certificate(dict_cfg)

    raw = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", None) or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if raw:
        raw = raw.strip()
        if raw:
            # try base64 then raw json
            try:
                data = json.loads(base64.b64decode(raw).decode("utf-8"))
            except Exception:
                data = json.loads(raw)
            if data.get("type") != "service_account" or "private_key" not in data:
                raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON ne correspond pas à une clé service_account.")
            return credentials.Certificate(data)

    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or getattr(settings, "USE_GOOGLE_APPLICATION_DEFAULT", False):
        return credentials.ApplicationDefault()

    return None
def _ensure_initialized() -> firebase_admin.App:
    """
    Initialise **l’app par défaut** (sans name=) exactement une fois.
    """
    # Si une app par défaut existe déjà, on la réutilise
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass  # pas d’app par défaut

    # Pas d’app par défaut -> on l’initialise
    cred = _build_credential()
    if cred is None:
        raise RuntimeError(
            "Firebase non configuré. Fournis l’un de : "
            "FIREBASE_SERVICE_ACCOUNT_PATH, FIREBASE_SERVICE_ACCOUNT_DICT, "
            "FIREBASE_SERVICE_ACCOUNT_JSON (JSON brut ou base64), "
            "ou GOOGLE_APPLICATIONS_CREDENTIALS + USE_GOOGLE_APPLICATION_DEFAULT."
        )
    # ⚠️ NE PAS passer de 'name=' ici -> crée l'app **par défaut**
    return firebase_admin.initialize_app(cred)
#     if firebase_admin._apps:
#         return
#     cred = _build_credential()
#     if cred is not None:
#         firebase_admin.initialize_app(cred, name=app_name)
#     else:
#         raise RuntimeError(
#             "Firebase non configuré. Fournis l’un de : "
#             "FIREBASE_SERVICE_ACCOUNT_PATH, FIREBASE_SERVICE_ACCOUNT_DICT, "
#             "FIREBASE_SERVICE_ACCOUNT_JSON (JSON brut ou base64), "
#             "ou configure GOOGLE_APPLICATION_CREDENTIALS / USE_GOOGLE_APPLICATION_DEFAULT."
#         )
#

# (facultatif) Ajoute ce helper pour tester si c'est OK
def is_configured() -> bool:
    try:
        _ensure_initialized()
        return True
    except Exception:
        return False


# -----------------------------
# Helpers génériques
# -----------------------------

_TOPIC_RE = re.compile(r"[^A-Za-z0-9_-]")

def _normalize_topic(topic: str) -> str:
    """
    Nettoie le topic pour respecter la contrainte FCM.
    """
    topic = (topic or "").strip()
    topic = topic.replace(" ", "_")
    topic = _TOPIC_RE.sub("_", topic)
    return topic or "default"

def _str_dict(d: Optional[Dict]) -> Dict[str, str]:
    return {str(k): str(v) for k, v in (d or {}).items()}

def _retryable_error(code: Optional[str]) -> bool:
    """
    Erreurs transitoires que l’on peut retenter.
    """
    return code in {"internal", "unavailable", "deadline-exceeded", "unknown"}

def _sleep_backoff(attempt: int, base: float = 0.3, cap: float = 3.0):
    delay = min(cap, base * (2 ** (attempt - 1)))  # 0.3, 0.6, 1.2, 2.4, 3.0…
    time.sleep(delay)

# -----------------------------
# Options plateforme
# -----------------------------

def _android_config(
    ttl_seconds: Optional[int] = None,
    priority_high: bool = True,
    channel_id: Optional[str] = None,
):
    # FCM max TTL is 4 weeks
    MAX_TTL = 28 * 24 * 3600  # seconds
    ttl = None
    if ttl_seconds is not None:
        ttl_seconds = max(0, min(int(ttl_seconds), MAX_TTL))
        ttl = timedelta(seconds=ttl_seconds)

    return messaging.AndroidConfig(
        priority="high" if priority_high else "normal",
        ttl=ttl,
        notification=messaging.AndroidNotification(channel_id=channel_id) if channel_id else None,
    )

def _apns_config(
    ttl_seconds: Optional[int] = None,
    sound: Optional[str] = "default",
    mutable_content: bool = False,
):
    headers = {}
    if ttl_seconds:
        headers["apns-expiration"] = str(int(time.time()) + int(ttl_seconds))
    payload = messaging.APNSPayload(
        aps=messaging.Aps(sound=sound, mutable_content=mutable_content)
    )
    return messaging.APNSConfig(headers=headers or None, payload=payload)

# -----------------------------
# Envois unitaires
# -----------------------------

def send_to_token(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
    *,
    ttl_seconds: Optional[int] = 3600,
    android_channel_id: Optional[str] = None,
    dry_run: bool = False,
    max_retries: int = 3,
):
    _ensure_initialized()
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=_str_dict(data),
        token=token,
        android=_android_config(ttl_seconds, True, android_channel_id),
        apns=_apns_config(ttl_seconds),
    )
    # retries
    attempt = 0
    while True:
        attempt += 1
        try:
            return messaging.send(msg, dry_run=dry_run)
        except Exception as e:  # firebase_admin._messaging_utils.ApiCallError
            code = getattr(e, "code", None)
            if attempt < max_retries and _retryable_error(str(code).lower() if code else None):
                _sleep_backoff(attempt)
                continue
            raise

def send_to_topic(
    topic: str,
    title: str,
    body: str,
    data: dict | None = None,
    *,
    ttl_seconds: Optional[int] = 3600,
    android_channel_id: Optional[str] = None,
    dry_run: bool = False,
    max_retries: int = 3,
):
    _ensure_initialized()
    norm = _normalize_topic(topic)
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=_str_dict(data),
        topic=norm,
        android=_android_config(ttl_seconds, True, android_channel_id),
        apns=_apns_config(ttl_seconds),
    )
    attempt = 0
    while True:
        attempt += 1
        try:
            return messaging.send(msg, dry_run=dry_run)
        except Exception as e:
            code = getattr(e, "code", None)
            if attempt < max_retries and _retryable_error(str(code).lower() if code else None):
                _sleep_backoff(attempt)
                continue
            raise

def send_condition(
    condition: str,
    title: str,
    body: str,
    data: dict | None = None,
    *,
    ttl_seconds: Optional[int] = 3600,
    dry_run: bool = False,
):
    """
    Envoi via condition FCM (ex: "'eglise_1' in topics || 'eglise_2' in topics").
    Pratique pour du ciblage multi-topics.
    """
    _ensure_initialized()
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=_str_dict(data),
        condition=condition,
        android=_android_config(ttl_seconds),
        apns=_apns_config(ttl_seconds),
    )
    return messaging.send(msg, dry_run=dry_run)

# -----------------------------
# Envois en batch / multicast
# -----------------------------

def send_multicast_to_tokens(
    tokens: Iterable[str],
    title: str,
    body: str,
    data: dict | None = None,
    *,
    ttl_seconds: Optional[int] = 3600,
    android_channel_id: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[int, List[Tuple[str, Optional[str]]]]:
    """
    Envoi à plusieurs tokens (jusqu’à 500 par batch).
    Retourne: (nb_succès, liste (token, error_code|None)).
    """
    _ensure_initialized()
    tokens = [t for t in tokens if t]
    if not tokens:
        return 0, []

    BATCH = 500
    total_ok = 0
    outcomes: List[Tuple[str, Optional[str]]] = []

    for i in range(0, len(tokens), BATCH):
        chunk = tokens[i : i + BATCH]
        msg = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=_str_dict(data),
            tokens=chunk,
            android=_android_config(ttl_seconds, True, android_channel_id),
            apns=_apns_config(ttl_seconds),
        )
        resp = messaging.send_multicast(msg, dry_run=dry_run)
        total_ok += resp.success_count
        # Aligner les erreurs au même index que les tokens
        for idx, resp_item in enumerate(resp.responses):
            err_code = None
            if not resp_item.success:
                err = resp_item.exception
                err_code = getattr(err, "code", "unknown")
            outcomes.append((chunk[idx], err_code if err_code else None))

    return total_ok, outcomes

def send_batch_messages(
    messages: List[messaging.Message],
    *,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """
    Envoi d’une liste de messages (max 500 par appel).
    Retourne (success_count, failure_count) cumulés.
    """
    _ensure_initialized()
    if not messages:
        return 0, 0

    BATCH = 500
    ok = fail = 0
    for i in range(0, len(messages), BATCH):
        chunk = messages[i : i + BATCH]
        resp = messaging.send_all(chunk, dry_run=dry_run)
        ok += resp.success_count
        fail += resp.failure_count
    return ok, fail

# -----------------------------
# Helpers "Verset du Jour"
# -----------------------------

def verse_title() -> str:
    return "Verset du jour"

def verse_body(reference: str, text: str, *, max_text_len: int = 140) -> str:
    text = " ".join((text or "").split())
    if len(text) > max_text_len:
        text = text[: max_text_len - 1].rstrip() + "…"
    return f"{reference} — {text}"

def verse_data_payload(
    reference: str,
    text: str,
    *,
    date_str: str,
    version: str,
    lang: str,
) -> Dict[str, str]:
    return _str_dict(
        {
            "type": "VERSE_DU_JOUR",
            "reference": reference,
            "text": text,
            "date": date_str,
            "version": version,
            "lang": lang,
        }
    )

def send_verse_to_eglise_topic(
    eglise_id: int,
    *,
    reference: str,
    text: str,
    date_str: str,
    version: str,
    lang: str,
    dry_run: bool = False,
):
    """
    Raccourci: envoie la notif du VDJ vers /topics/eglise_{id}
    """
    topic = f"eglise_{eglise_id}"
    title = verse_title()
    body = verse_body(reference, text)
    data = verse_data_payload(reference, text, date_str=date_str, version=version, lang=lang)
    return send_to_topic(topic, title, body, data, dry_run=dry_run)

# from __future__ import annotations
# import os
# import json
# import base64
# import firebase_admin
# from firebase_admin import credentials, messaging
# from django.conf import settings
#
# def _build_credential():
#     """
#     Construit un credentials.Credential depuis:
#     - settings.FIREBASE_SERVICE_ACCOUNT_PATH
#     - settings.FIREBASE_CREDENTIALS_JSON (dict)
#     - settings.FIREBASE_SERVICE_ACCOUNT_B64 (base64 JSON)
#     - GOOGLE_APPLICATION_CREDENTIALS (ADC)
#     Retourne None si ADC doit être utilisé sans args.
#     """
#     path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_PATH", None)
#     creds_dict = getattr(settings, "FIREBASE_CREDENTIALS_JSON", None)
#     b64 = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_B64", None) or os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
#     adc = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or getattr(settings, "USE_GOOGLE_APPLICATION_DEFAULT", None)
#
#     if path:
#         return credentials.Certificate(path)
#
#     if creds_dict:
#         return credentials.Certificate(creds_dict)
#
#     if b64:
#         try:
#             data = json.loads(base64.b64decode(b64).decode("utf-8"))
#             return credentials.Certificate(data)
#         except Exception as e:
#             raise ValueError(f"FIREBASE_SERVICE_ACCOUNT_B64 invalide: {e}")
#
#     if adc:
#         # Application Default Credentials; nécessite la variable GOOGLE_APPLICATION_CREDENTIALS
#         return credentials.ApplicationDefault()
#
#     # Rien fourni → on laisse firebase_admin.initialize_app() sans credentials
#     # (échouera si aucune ADC dispo). Mieux vaut lever une erreur explicite :
#     return None
#
# def _ensure_initialized():
#     """Initialise l'app Firebase une seule fois, proprement."""
#     if firebase_admin._apps:
#         return
#     cred = _build_credential()
#     if cred is not None:
#         firebase_admin.initialize_app(cred)
#     else:
#         # Donne un message explicite au lieu d'un None cryptique
#         raise RuntimeError(
#             "Firebase non configuré. "
#             "Renseigne FIREBASE_SERVICE_ACCOUNT_PATH, FIREBASE_CREDENTIALS_JSON, "
#             "FIREBASE_SERVICE_ACCOUNT_B64 ou GOOGLE_APPLICATION_CREDENTIALS."
#         )
#
# def send_to_token(token: str, title: str, body: str, data: dict | None = None):
#     _ensure_initialized()
#     message = messaging.Message(
#         notification=messaging.Notification(title=title, body=body),
#         data={k: str(v) for k, v in (data or {}).items()},
#         token=token,
#     )
#     return messaging.send(message)
#
# def send_to_topic(topic: str, title: str, body: str, data: dict | None = None):
#     _ensure_initialized()
#     # FCM demande un topic "nettoyé" (lettres, chiffres, _-)
#     norm = topic.strip().replace(" ", "_")
#     message = messaging.Message(
#         notification=messaging.Notification(title=title, body=body),
#         data={k: str(v) for k, v in (data or {}).items()},
#         topic=norm,
#     )
#     return messaging.send(message)