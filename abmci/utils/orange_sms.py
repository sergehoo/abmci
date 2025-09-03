import base64
import json
import logging
import os
import requests

logger = logging.getLogger(__name__)

ORANGE_TOKEN_URL = os.environ.get("ORANGE_TOKEN_URL", "https://api.orange.com/oauth/v3/token")
ORANGE_SMS_URL = os.environ.get(
    "ORANGE_SMS_URL",
    "https://api.orange.com/smsmessaging/v1/outbound/{}/requests"
)
ORANGE_SMS_CLIENT_ID = os.environ.get("ORANGE_SMS_CLIENT_ID", "")
ORANGE_SMS_CLIENT_SECRET = os.environ.get("ORANGE_SMS_CLIENT_SECRET", "")
ORANGE_SMS_SENDER = os.environ.get("ORANGE_SMS_SENDER", "")  # numéro émetteur au format international

def _get_access_token() -> str:
    """
    OAuth Client Credentials pour Orange.
    """
    if not ORANGE_SMS_CLIENT_ID or not ORANGE_SMS_CLIENT_SECRET:
        raise RuntimeError("Orange SMS client id/secret manquant dans l'env.")

    auth = f"{ORANGE_SMS_CLIENT_ID}:{ORANGE_SMS_CLIENT_SECRET}"
    b64 = base64.b64encode(auth.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}

    resp = requests.post(ORANGE_TOKEN_URL, headers=headers, data=data, timeout=10)
    try:
        resp.raise_for_status()
    except Exception:
        logger.exception("Échec token Orange: %s %s", resp.status_code, resp.text)
        raise

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Token Orange introuvable dans la réponse")
    return token

def send_sms(to_e164: str, message: str) -> None:
    """
    Envoie un SMS via Orange. `to_e164` doit être au format 'tel:+225...'
    """
    if not ORANGE_SMS_SENDER:
        raise RuntimeError("ORANGE_SMS_SENDER manquant")

    token = _get_access_token()

    url = ORANGE_SMS_URL.format(ORANGE_SMS_SENDER)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "outboundSMSMessageRequest": {
            "address": f"tel:{to_e164.replace('tel:', '')}",
            "senderAddress": f"tel:{ORANGE_SMS_SENDER}",
            "senderName": "IPCI",
            "outboundSMSTextMessage": {
                "message": message[:160]  # tronque si nécessaire
            }
        }
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    try:
        resp.raise_for_status()
    except Exception:
        logger.exception("Échec SMS vers %s: %s %s", to_e164, resp.status_code, resp.text)
        raise