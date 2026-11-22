# prayers/services/notifications.py
from __future__ import annotations
from typing import Iterable, Set
from django.db import transaction
from django.contrib.auth import get_user_model
import logging

from abmci.notifications.fcm import send_to_user  # ⬅️ utilise la bonne fonction

logger = logging.getLogger(__name__)
User = get_user_model()


def push_inapp_notification(user_ids: Iterable[int], *, type: str, title: str, body: str, data: dict):
    """
    Notification in-app (fidele.Notification + une entrée NotificationUser par destinataire, lue par
    /api/user-notifications/) puis push FCM sur le topic user_{id}. Retourne (envoyés, échecs).
    """
    from fidele.models import Notification, NotificationUser  # import local : fidele.models importe abmci.notifications

    user_ids = {uid for uid in user_ids if uid}
    if not user_ids:
        return 0, 0
    notif = Notification.objects.create(type=type, title=title, body=body, data=data)
    ok = fail = 0
    for uid in user_ids:
        try:
            NotificationUser.objects.get_or_create(user_id=uid, notification=notif)
            send_to_user(User(pk=uid), title=title, body=body, data=data)
            ok += 1
        except Exception as e:
            fail += 1
            logger.exception("[NOTIF][user_%s] FAILED: %r", uid, e)
    return ok, fail

def _title_for_comment(prayer) -> str:
    return "Nouveau commentaire"

def _body_for_comment(prayer, comment) -> str:
    author = comment.user.get_full_name() or comment.user.username or "Quelqu’un"
    title = (prayer.title or "Sujet de prière").strip()
    content = " ".join((comment.content or "").split())
    if len(content) > 120:
        content = content[:119].rstrip() + "…"
    return f"{author} a commenté « {title} » : {content}"

def _payload_for_comment(prayer, comment) -> dict:
    return {
        "type": "COMMENT_NEW",
        "prayer_id": str(prayer.id),
        "comment_id": str(comment.id),
        # 🔗 ajoute un deeplink pour router côté app
        "deeplink": f"ac://prayer/{prayer.id}?focus={comment.id}",
    }

def recipients_for_new_comment(prayer, new_comment) -> Set[int]:
    recips: Set[int] = set()
    if getattr(prayer, "user_id", None):
        recips.add(prayer.user_id)
    qs = prayer.comments.values_list("user_id", flat=True).distinct()
    recips.update(uid for uid in qs if uid)
    if getattr(new_comment, "user_id", None):
        recips.discard(new_comment.user_id)
    return recips

def notify_new_comment(prayer, comment):
    """
    Crée des notifications DB + push FCM APRÈS le commit.
    """
    recips = recipients_for_new_comment(prayer, comment)
    if not recips:
        return

    title = _title_for_comment(prayer)
    body = _body_for_comment(prayer, comment)
    data = _payload_for_comment(prayer, comment)

    def _send():
        ok, fail = push_inapp_notification(recips, type="COMMENT_NEW", title=title, body=body, data=data)
        logger.info("[NOTIF][COMMENT] sent=%s, failed=%s", ok, fail)

    transaction.on_commit(_send)