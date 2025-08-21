# prayers/services/notifications.py
from __future__ import annotations
from typing import Iterable, Set
from django.db import transaction
from django.contrib.auth import get_user_model

from notifications.models import Notification
# from abmci.notifications.fcm import send_to_user_topic

User = get_user_model()

def _title_for_comment(prayer) -> str:
    # titre court
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
    }

def recipients_for_new_comment(prayer, new_comment) -> Set[int]:
    """
    - auteur du sujet
    - tous les commentateurs précédents
    - exclure l’auteur du nouveau commentaire
    """
    recips: Set[int] = set()

    if getattr(prayer, "user_id", None):
        recips.add(prayer.user_id)

    # Tous les commentateurs distincts du thread
    qs = prayer.comments.values_list("user_id", flat=True).distinct()
    recips.update(uid for uid in qs if uid)

    # Exclure l'auteur du nouveau commentaire
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
        ok = fail = 0
        for uid in recips:
            try:
                # Sauvegarde locale (pour l’onglet Notifications)
                Notification.objects.create(
                    user_id=uid,
                    type="COMMENT_NEW",
                    title=title,
                    body=body,
                    data=data,
                )
                # Push FCM topic utilisateur
                send_to_user_topic(uid, title, body, data)
                ok += 1
            except Exception as e:
                fail += 1
                # remplace par ton logger
                print(f"[NOTIF][user_{uid}] FAILED: {e!r}")
        print(f"[NOTIF][COMMENT] sent={ok}, failed={fail}")

    # Important: push après que le commentaire soit réellement committé
    transaction.on_commit(_send)