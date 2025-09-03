# abmci/utils/orange_sms.py
import base64
import json
import logging
import os
import requests

logger = logging.getLogger(__name__)

ORANGE_TOKEN_URL = os.environ.get("ORANGE_TOKEN_URL", "https://api.orange.com/oauth/v3/token")
# ⚠️ Tu peux mettre dans l'env au choix:
#   - https://api.orange.com/smsmessaging/v1/outbound/{sender_path}/requests
#   - https://api.orange.com/smsmessaging/v1/outbound/{}/requests
#   - https://api.orange.com/smsmessaging/v1/outbound/requests   (sans placeholder)
ORANGE_SMS_URL = os.environ.get(
    "ORANGE_SMS_URL",
    "https://api.orange.com/smsmessaging/v1/outbound/{sender_path}/requests",
)

ORANGE_SMS_CLIENT_ID = os.environ.get("ORANGE_SMS_CLIENT_ID", "")
ORANGE_SMS_CLIENT_SECRET = os.environ.get("ORANGE_SMS_CLIENT_SECRET", "")
# 👉 MSISDN (+225XXXXXXXX) ou shortcode, SANS 'tel:'
ORANGE_SMS_SENDER = os.environ.get("ORANGE_SMS_SENDER", "")


def _normalize_msisdn(value: str) -> str:
    v = (value or "").strip()
    if v.lower().startswith("tel:"):
        v = v[4:]
    return v


def _sender_address() -> str:
    sender = _normalize_msisdn(ORANGE_SMS_SENDER)
    if not sender:
        raise RuntimeError("ORANGE_SMS_SENDER manquant")
    # shortcode (ex '1234') → OK
    if sender.isdigit():
        return f"tel:{sender}"
    # MSISDN → doit commencer par '+'
    if not sender.startswith("+"):
        raise RuntimeError("ORANGE_SMS_SENDER doit être un MSISDN commençant par '+' ou un shortcode numérique")
    return f"tel:{sender}"


def _build_url(sender_address: str) -> str:
    tmpl = ORANGE_SMS_URL
    # 1) placeholder nommé
    if "{sender_path}" in tmpl:
        return tmpl.format(sender_path=sender_address)
    # 2) placeholder positionnel
    if "{}" in tmpl:
        return tmpl.format(sender_address)
    # 3) pas de placeholder → on insère proprement
    if tmpl.endswith("/"):
        return f"{tmpl}{sender_address}/requests"
    if tmpl.endswith("/requests"):
        # déjà complet sans sender → on insère avant 'requests'
        return tmpl.replace("/requests", f"/{sender_address}/requests")
    # fallback simple
    return f"{tmpl.rstrip('/')}/{sender_address}/requests"


def _get_access_token() -> str:
    if not ORANGE_SMS_CLIENT_ID or not ORANGE_SMS_CLIENT_SECRET:
        raise RuntimeError("Orange SMS client id/secret manquant dans l'env.")

    auth = f"{ORANGE_SMS_CLIENT_ID}:{ORANGE_SMS_CLIENT_SECRET}"
    b64 = base64.b64encode(auth.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {"grant_type": "client_credentials"}

    resp = requests.post(ORANGE_TOKEN_URL, headers=headers, data=data, timeout=15)
    try:
        resp.raise_for_status()
    except Exception:
        logger.error("Échec token Orange (%s): %s", resp.status_code, resp.text)
        raise

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Token Orange introuvable dans la réponse")
    return token


def send_sms(to_e164: str, message: str) -> None:
    """
    Envoie un SMS via Orange, URL de type:
      https://api.orange.com/smsmessaging/v1/outbound/tel:+225734201/requests
    """
    sender_address = _sender_address()  # ex 'tel:+225734201' ou 'tel:1234'
    url = _build_url(sender_address)

    token = _get_access_token()

    # Destinataire au format E.164 '+225...'
    dest = (to_e164 or "").strip()
    if dest.lower().startswith("tel:"):
        dest = dest[4:]
    if not dest.startswith("+"):
        raise ValueError(f"Destinataire non E.164: {to_e164}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "outboundSMSMessageRequest": {
            "address": f"tel:{dest}",
            "senderAddress": sender_address,  # doit matcher le segment du path
            "outboundSMSTextMessage": {"message": message[:160]},
        }
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
    if resp.status_code >= 400:
        logger.error(
            "Orange SMS %s\nURL: %s\nPayload: %s\nResponse: %s",
            resp.status_code,
            url,
            json.dumps(payload, ensure_ascii=False),
            resp.text,
        )
        resp.raise_for_status()