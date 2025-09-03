import base64
import json
import logging
import os
import requests

logger = logging.getLogger(__name__)

ORANGE_TOKEN_URL = os.environ.get("ORANGE_TOKEN_URL", "https://api.orange.com/oauth/v3/token")
ORANGE_SMS_URL = os.environ.get(
    "ORANGE_SMS_URL",
    "https://api.orange.com/smsmessaging/v1/outbound/{sender_path}/requests"
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
def _normalize_msisdn(value: str) -> str:
    """
    Retourne un identifiant d’émetteur sans préfixe 'tel:'.
    Exemples acceptés en entrée: '+225734201', 'tel:+225734201', '1234' (shortcode).
    """
    v = (value or "").strip()
    if v.lower().startswith("tel:"):
        v = v[4:]
    return v


def _sender_address() -> str:
    """
    Construit la forme 'tel:+225xxxxxxx' ou 'tel:<shortcode>' à utiliser
    à la fois dans le PATH et dans le payload.
    """
    sender = _normalize_msisdn(ORANGE_SMS_SENDER)
    if not sender:
        raise RuntimeError("ORANGE_SMS_SENDER manquant")
    # MSISDN → doit commencer par '+', sinon on suppose un shortcode
    if sender.isdigit():
        # shortcode (ex: '1234')
        return f"tel:{sender}"
    if not sender.startswith("+"):
        raise RuntimeError("ORANGE_SMS_SENDER doit commencer par '+' (MSISDN) ou être un shortcode numérique")
    return f"tel:{sender}"
def send_sms(to_e164: str, message: str) -> None:
    """
    Envoie un SMS via Orange.
    - to_e164: ex '+2250700000000' (SANS 'tel:')
    Respecte le format d’URL: .../outbound/tel:+225734201/requests
    """
    sender_address = _sender_address()  # ex 'tel:+225734201' ou 'tel:1234'
    url = ORANGE_SMS_URL.format(sender_path=sender_address)

    token = _get_access_token()

    # Normalise le destinataire: on veut '+225...'
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
            "address": f"tel:{dest}",        # <- 'tel:+225...'
            "senderAddress": sender_address, # <- 'tel:+225734201' (exactement comme dans le path)
            "outboundSMSTextMessage": {"message": message[:160]},
        }
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
    if resp.status_code >= 400:
        logger.error("Orange SMS %s\nURL: %s\nPayload: %s\nResponse: %s",
                     resp.status_code, url, json.dumps(payload, ensure_ascii=False), resp.text)
        resp.raise_for_status()
#
# def send_sms(to_e164: str, message: str) -> None:
#     """
#     Envoie un SMS via Orange. `to_e164` doit être au format 'tel:+225...'
#     """
#     if not ORANGE_SMS_SENDER:
#         raise RuntimeError("ORANGE_SMS_SENDER manquant")
#
#     token = _get_access_token()
#
#     url = ORANGE_SMS_URL.format(ORANGE_SMS_SENDER)
#     headers = {
#         "Authorization": f"Bearer {token}",
#         "Content-Type": "application/json",
#     }
#     payload = {
#         "outboundSMSMessageRequest": {
#             "address": f"tel:{to_e164.replace('tel:', '')}",
#             "senderAddress": f"tel:{ORANGE_SMS_SENDER}",
#             "senderName": "IPCI",
#             "outboundSMSTextMessage": {
#                 "message": message[:160]  # tronque si nécessaire
#             }
#         }
#     }
#
#     resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
#     try:
#         resp.raise_for_status()
#     except Exception:
#         logger.exception("Échec SMS vers %s: %s %s", to_e164, resp.status_code, resp.text)
#         raise