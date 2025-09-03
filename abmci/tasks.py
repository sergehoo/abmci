import logging
from datetime import date
from io import BytesIO
from typing import Iterable

from PIL import UnidentifiedImageError
from celery import shared_task, group
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db import transaction
from PIL import Image, UnidentifiedImageError
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from phonenumber_field.phonenumber import to_python

from event.models import Evenement, ParticipationEvenement
from event.services.events import generate_recurrences_for_parent
from event.services.scheduling_verse import schedule_vod_for_period, pick_candidate_verses
from fidele.models import Eglise, BibleVersion, ProblemReport, Role, Fidele
from fidele.views import process_account_deletion_request
from fidele.vod_smart import pick_smart_daily_verse_for_eglise
# from .models import ParticipationEvenement
from .notifications.fcm import send_to_topic, send_to_user
from .utils.orange_sms import send_sms


@shared_task
def send_event_reminders():
    # Trouver les événements à venir dans les prochains jours
    upcoming_events = Evenement.objects.filter(
        date_debut__gt=timezone.now(),
        date_debut__lte=timezone.now() + timezone.timedelta(days=7)
    )

    for event in upcoming_events:
        participants = ParticipationEvenement.objects.filter(evenement=event)

        for participation in participants:
            # Envoyer une notification à chaque participant
            subject = f"Rappel: {event.titre}"
            message = render_to_string('emails/event_reminder.txt', {
                'event': event,
                'participation': participation
            })

            send_mail(
                subject,
                message,
                'no-reply@votredomaine.com',
                [participation.fidele.user.email],
                fail_silently=False,
            )



@shared_task
def update_daily_verses_for_all_eglisess(version_code="LSG", language="fr"):
    """
    Tâche planifiée (via django-celery-beat) qui sélectionne et enregistre
    un verset pour chaque église (variation déterministe + anti-répétition).
    """
    count = 0
    today = timezone.localdate()
    for e in Eglise.objects.all():
        try:
            with transaction.atomic():
                pick_smart_daily_verse_for_eglise(
                    eglise=e,
                    version_code=version_code,
                    language=language,
                    on_date=today,
                )
                count += 1
        except Exception as ex:
            # logge toi-même si besoin
            print(f"[VOD] {e.id}: {ex}")
    return count
@shared_task
def task_process_account_deletion_request(req_id):
    process_account_deletion_request(req_id)

CHUNK_SIZE = 200
BANNER_TARGET_SIZE = (1420, 560)


def resize_image_field(field_file, target_size=BANNER_TARGET_SIZE):
    """
    Redimensionne un ImageField quelle que soit la storage backend.
    - Lit via default_storage.open(field_file.name)
    - Sauvegarde en réécrivant le même nom (overwrite)
    """
    if not field_file:
        return

    # lire l’image depuis le storage
    try:
        with default_storage.open(field_file.name, 'rb') as f:
            img = Image.open(f)
            img.load()
    except (FileNotFoundError, UnidentifiedImageError, OSError):
        return

    # resize
    img = img.resize(target_size, Image.LANCZOS)

    # encoder (conserver format si possible, sinon PNG)
    fmt = (img.format or "PNG").upper()
    if fmt not in ("JPEG", "JPG", "PNG", "WEBP"):
        fmt = "PNG"

    buf = BytesIO()
    save_kwargs = {}
    if fmt in ("JPEG", "JPG"):
        save_kwargs["quality"] = 90
        save_kwargs["optimize"] = True
    img.save(buf, format=fmt, **save_kwargs)
    buf.seek(0)

    # réécrit le fichier au même emplacement
    content = ContentFile(buf.read())
    default_storage.save(field_file.name, content)  # overwrite si storage le supporte


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def generate_recurrences_task(self, parent_id: int):
    try:
        parent = Evenement.objects.get(pk=parent_id)
    except Evenement.DoesNotExist:
        return {"created": 0, "children": []}

    created_ids = generate_recurrences_for_parent(parent)

    if created_ids:
        # fan-out en chunks
        subtasks = []
        for i in range(0, len(created_ids), CHUNK_SIZE):
            chunk = created_ids[i:i + CHUNK_SIZE]
            subtasks.append(generate_qr_and_resize_chunk.s(chunk))
        group(subtasks).delay()

    return {"created": len(created_ids), "children": created_ids}


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def generate_qr_and_resize_chunk(self, ids: list[int]):
    """
    Backfill QR + resize bannière pour une liste d'IDs.
    - iterator() pour limiter la mémoire
    - sauvegarde uniquement qr_code (la bannière est réécrite en place)
    """
    qs = Evenement.objects.filter(id__in=ids).only(
        "id", "code", "qr_code", "banner"
    ).iterator()

    updated = 0
    for ev in qs:
        # QR
        if not ev.qr_code:
            ev.generate_and_save_qr_code(ev.code)
            ev.save(update_fields=["qr_code"])
            updated += 1

        # Banner resize (si présente)
        if ev.banner:
            try:
                resize_image_field(ev.banner)
            except Exception:
                # on ignore l'erreur de resize, le QR reste OK
                pass

    return {"processed": len(ids), "qr_updated": updated}


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def schedule_vod_task(self,payload: dict):
    """
    payload = {
      "eglise_ids": [1,2],
      "start": "2025-09-01",
      "end": "2025-09-30",
      "version_id": 1,
      "language": "fr",
      "keywords": ["amour","grâce"],
      "books": ["Psaumes","Proverbes"],
      "context_key": "DEFAULT",
      "avoid_recent_days": 90,
      "overwrite_existing": False,
      "shuffle": True,
    }
    """
    start = date.fromisoformat(payload["start"])
    end = date.fromisoformat(payload["end"])
    eglises = list(Eglise.objects.filter(id__in=payload["eglise_ids"]))
    version = BibleVersion.objects.get(id=payload["version_id"])
    keywords = payload.get("keywords") or []
    books = payload.get("books") or []
    candidates = pick_candidate_verses(
        version=version,
        language=payload.get("language","fr"),
        keywords=keywords,
        books=books,
        limit=None,
        shuffle=payload.get("shuffle", True),
    )
    res = schedule_vod_for_period(
        eglises=eglises,
        start=start,
        end=end,
        version=version,
        language=payload.get("language","fr"),
        candidates=candidates,
        context_key=payload.get("context_key") or "DEFAULT",
        avoid_recent_days=int(payload.get("avoid_recent_days") or 0),
        overwrite_existing=bool(payload.get("overwrite_existing") or False),
    )
    return {"created_by_eglise": res, "total_created": sum(res.values())}



@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def notify_problem_created(self, problem_id: int):
    try:
        pr = ProblemReport.objects.select_related("eglise", "reporter__user", "assignee").get(pk=problem_id)
    except ProblemReport.DoesNotExist:
        return

    title = f"Nouveau signalement: {pr.title}"
    body = f"{pr.reporter.user.first_name} {pr.reporter.user.last_name} – {pr.get_severity_display()}"

    # Topic par église (ex: "eglise_12")
    topic = f"eglise_{pr.eglise_id}_care"
    send_to_topic(topic, title=title, body=body, data={"problem_id": str(pr.id), "type": "problem_created"})

    # Notifier le responsable direct
    if pr.assignee:
        send_to_user(pr.assignee, title=title, body=body, data={"problem_id": str(pr.id)})





logger = logging.getLogger(__name__)

def _fmt_date(d):
    return d.strftime("%d/%m/%Y") if d else "—"

def _build_message(report: ProblemReport) -> str:
    reporter_user = getattr(report.reporter, "user", None)
    full_name = ""
    if reporter_user:
        full_name = f"{reporter_user.first_name} {reporter_user.last_name}".strip()
        reporter_contact = f"{reporter_user.fidele.phone}"
    full_name = full_name or "Un fidèle"
    due = _fmt_date(report.due_date)
    return (
        f"Bonjour, le fidèle {full_name} a signalé {report.category.name} « {report.title} » "
        f"(échéance: {due}). Merci de le contacter pour plus d'informations au {reporter_contact}."
    )

def _pastors_queryset(report: ProblemReport):
    try:
        role_pasteur = Role.objects.get(code="PASTEUR")
    except Role.DoesNotExist:
        return Fidele.objects.none()

    return (
        Fidele.objects
        .filter(
            roles=role_pasteur,
            eglise=report.eglise,
            phone__isnull=False,
        )
        .distinct()
    )

def _e164_numbers(fideles: Iterable[Fidele]) -> list[str]:
    numbers = []
    for f in fideles:
        if not f.phone:
            continue
        p = to_python(f.phone)
        if p and p.is_valid():
            numbers.append(p.as_e164)  # ex: +2250700000000
    return numbers

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_problem_sms_to_pastors(self, report_id: int) -> dict:
    """
    Envoie le SMS aux pasteurs (rôle PASTEUR) de la même église que le report.
    - retry exponentiel auto (retry_backoff=True)
    - max_retries=5
    Renvoie un petit résumé {sent: n, to: [...]} pour logs.
    """
    try:
        report = ProblemReport.objects.select_related("reporter__user", "eglise").get(pk=report_id)
    except ProblemReport.DoesNotExist:
        logger.warning("Report %s introuvable pour envoi SMS", report_id)
        return {"sent": 0, "to": []}

    msg = _build_message(report)
    qs = _pastors_queryset(report)
    recipients = _e164_numbers(qs)

    sent = 0
    for to in recipients:
        try:
            send_sms(to, msg)
            sent += 1
        except Exception as e:
            logger.exception("Échec envoi SMS à %s pour report %s: %s", to, report_id, e)
            # On laisse l’autoretry gérer les cas transitoires.
            # Si tu veux retry par numéro, tu peux lever ici pour stopper la task et replanifier.
            continue

    logger.info("SMS problème #%s envoyé à %d/%d pasteurs", report_id, sent, len(recipients))
    return {"sent": sent, "to": recipients}