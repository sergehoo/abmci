# # abmci/notifications/fcm.py
# abmci/notifications/fcm.py
from __future__ import annotations
import os
import re
import json
import base64
import time
from datetime import timedelta
from typing import Iterable, List, Optional, Tuple, Dict, Mapping, Any

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

    if os.getenv("GOOGLE_APPLICATION_CREDENTIAL") or getattr(settings, "USE_GOOGLE_APPLICATION_DEFAULT", False):
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
        collapse_key: Optional[str] = None,
        image_url: Optional[str] = None,
        use_notification: bool = True,  # piloté au niveau appel
):
    MAX_TTL = 28 * 24 * 3600
    ttl = None
    if ttl_seconds is not None:
        ttl_seconds = max(0, min(int(ttl_seconds), MAX_TTL))
        ttl = timedelta(seconds=ttl_seconds)

    notif = None
    if use_notification:
        notif = messaging.AndroidNotification(
            channel_id=channel_id,
            image=image_url,
        )

    return messaging.AndroidConfig(
        priority="high" if priority_high else "normal",
        ttl=ttl,
        collapse_key=collapse_key,
        notification=notif,
    )


def _apns_config(
        ttl_seconds: Optional[int] = None,
        sound: Optional[str] = "default",
        mutable_content: bool = False,
        badge: Optional[int] = None,
        silent: bool = False,
):
    headers = {}
    if ttl_seconds:
        headers["apns-expiration"] = str(int(time.time()) + int(ttl_seconds))

    aps = messaging.Aps(
        sound=None if silent else sound,
        mutable_content=mutable_content,
        badge=badge,
        content_available=True if silent else None,
    )
    return messaging.APNSConfig(headers=headers or None, payload=messaging.APNSPayload(aps=aps))


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
        android_collapse_key: Optional[str] = None,
        android_image_url: Optional[str] = None,
        apns_badge: Optional[int] = None,
        silent: bool = False,
        use_notification: bool = False,  # défaut data-only
        dry_run: bool = False,
        max_retries: int = 3,
):
    _ensure_initialized()
    msg = messaging.Message(
        notification=(None if (silent or not use_notification) else messaging.Notification(title=title, body=body)),
        data=_str_dict(data),
        token=token,
        android=_android_config(ttl_seconds, True, android_channel_id, android_collapse_key, android_image_url,
                                use_notification and not silent),
        apns=_apns_config(ttl_seconds, badge=apns_badge, silent=silent),
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
        chunk = tokens[i: i + BATCH]
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
                if err_code in {"registration-token-not-registered", "invalid-argument"}:
                    # TODO: marquer ce token comme invalide en DB (ex: TokenDevice.objects.filter(token=chunk[idx]).update(active=False))
                    pass
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
        chunk = messages[i: i + BATCH]
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
            "type": "verse",
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
        android_channel_id="default_channel",
):
    """
    Raccourci: envoie la notif du VDJ vers /topics/eglise_{id}
    """
    topic = f"eglise_{eglise_id}"
    title = verse_title()
    body = verse_body(reference, text)
    data = verse_data_payload(reference, text, date_str=date_str, version=version, lang=lang)
    return send_to_topic(topic, title, body, data, dry_run=dry_run)


def send_to_user(user_or_fidele, *, title: str, body: str, data: Mapping[str, Any] | None = None,
                 dry_run: bool = False):
    """
    Envoi “direct” en s’appuyant sur un topic par utilisateur.
    Accepte un User OU un Fidele.
    """
    user_id = getattr(user_or_fidele, "id", None)
    if user_id is None and hasattr(user_or_fidele, "user"):
        user_id = user_or_fidele.user.id
    if not user_id:
        # pas d’ID exploitable → on ne peut pas router
        return
    topic = f"user_{user_id}"
    return send_to_topic(topic, title=title, body=body, data=data, dry_run=dry_run)
