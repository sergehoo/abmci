# donations/paystack.py
from __future__ import annotations

import hashlib, hmac, requests, uuid
from django.conf import settings


def make_reference(prefix="DON"):
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def to_base_units(amount_int: int) -> int:
    # Paystack attend des "base units" (×100) pour la plupart des devises
    # XOF/NGN → ×100
    return int(amount_int) * 100


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    # Paystack docs: HMAC-SHA512 du body JSON avec la SECRET_KEY
    if not signature:
        return False
    key = settings.PAYSTACK_SECRET_KEY or ""
    mac = hmac.new(key.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha512).hexdigest()
    return hmac.compare_digest(mac, signature)


def ps_headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def ps_initialize(amount_base, email, reference, callback_url, currency, metadata: dict | None = None, timeout=30):
    url = f"{settings.PAYSTACK_BASE_URL}/transaction/initialize"
    payload = {
        "amount": amount_base,
        "email": email,
        "reference": reference,
        "callback_url": callback_url,
        "currency": currency,
        "metadata": metadata or {},
    }
    r = requests.post(url, json=payload, headers=ps_headers(), timeout=timeout)
    return r


def ps_verify(reference: str, timeout=20):
    url = f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}"
    r = requests.get(url, headers=ps_headers(), timeout=timeout)
    return r
