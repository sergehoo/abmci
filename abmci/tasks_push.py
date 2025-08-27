# tasks_push.py
from celery import shared_task
from django.utils import timezone

from abmci.notifications.fcm import send_verse_to_eglise_topic
from fidele.models import Eglise, VerseOfDay


# from bible.models import VerseOfDay  # adapte le chemin
# from .fcm import send_verse_to_eglise_topic  # ta fonction existante

@shared_task(name="abmci.push_vod_daily")
def push_vod_daily():
    today = timezone.localdate()
    total = 0
    for e in Eglise.objects.all().only("id", "name"):
        vod = VerseOfDay.objects.filter(eglise=e, date=today).first()
        if not vod:
            continue
        # Construire le message
        title = f"Verset du jour – {e.name or 'ABMCI'}"
        body  = f"“{vod.text}” — {vod.reference}"

        # payload data pour deep-link (optionnel)
        data = {
            "type": "vod",
            "eglise_id": str(e.id),
            "date": str(today),
            "reference": vod.reference,
        }

        # Topic par église (ex: eglise_<id>)
        try:
            send_verse_to_eglise_topic(
                eglise_id=e.id,
                reference=vod.reference,
                text=vod.text,
                date_str=str(vod.date),
                version=vod.version,
                lang=vod.language,
                dry_run=False,
                # si ta fonction accepte "title/body/data", passe-les :
                title=title,
                body=body,
                data=data,
            )
            total += 1
        except Exception as exc:
            # log si besoin
            print(f"[FCM] fail eglise {e.id}: {exc!r}")
    return {"pushed": total}