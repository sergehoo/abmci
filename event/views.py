from __future__ import annotations

import json
import logging
from datetime import timedelta, datetime

from django.contrib import messages

from abmci.access import StaffRequiredMixin
from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect
from django.utils.http import urlencode
from django.views.generic import ListView, DetailView, TemplateView, DeleteView
from django.views.generic.edit import CreateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.utils import timezone
import qrcode
from PIL import Image
from io import BytesIO

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from event.eventForm import EvenementForm
from event.models import Evenement, ParticipationEvenement, TypeEvent
from reportlab.pdfgen import canvas
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework_simplejwt.tokens import RefreshToken
from firebase_admin import auth as fb_auth, _auth_utils
import phonenumbers
from abmci.tasks import generate_recurrences_task
from abmci.notifications.fcm import _ensure_initialized as _ensure_firebase_initialized
from allauth.utils import generate_unique_username
from fidele.models import Fidele

logger = logging.getLogger(__name__)

def generate_qr_code(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer)
    return buffer.getvalue()


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    try:
        p = phonenumbers.parse(phone, None)
        return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return phone

class FirebaseLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        """
        Body: { "id_token": "<Firebase ID token>" }
        """
        id_token = (request.data.get("id_token") or "").strip()
        if not id_token:
            return Response({"detail": "id_token manquant."}, status=400)

        try:
            _ensure_firebase_initialized()  # sans app Firebase par défaut, verify_id_token échouait toujours
            decoded = fb_auth.verify_id_token(id_token)
        except _auth_utils.ExpiredIdTokenError:
            return Response({"detail": "ID token expiré."}, status=401)
        except _auth_utils.InvalidIdTokenError:
            return Response({"detail": "ID token invalide."}, status=401)
        except Exception:
            logger.exception("Connexion Firebase : vérification du jeton impossible")
            return Response({"detail": "Vérification échouée."}, status=401)

        uid = decoded.get("uid")
        email = (decoded.get("email") or "").strip()
        email_verified = bool(decoded.get("email_verified", False))

        if not uid:
            return Response({"detail": "UID Firebase manquant."}, status=400)
        # Politique : une adresse non vérifiée ne sert ni à créer ni à rapprocher un compte
        if email and not email_verified:
            return Response({"detail": "E-mail non vérifié."}, status=403)

        # Rapprochement : firebase_uid est porté par Fidele (auth.User n'a ni firebase_uid ni phone_number)
        fidele = Fidele.objects.select_related("user").filter(firebase_uid=uid).first()
        user = fidele.user if fidele else None
        if user is None and email:
            # Sûr uniquement parce que Firebase garantit ici la possession de l'adresse (email_verified)
            user = User.objects.filter(email__iexact=email).first()
        if user is None:
            if not email:
                return Response({"detail": "Un e-mail vérifié est requis pour créer un compte."}, status=400)
            user = User.objects.create_user(username=generate_unique_username([email, "user"]), email=email)
            user.set_unusable_password()
            user.save(update_fields=["password"])

        fidele, _ = Fidele.objects.get_or_create(user=user)  # normalement créé par le signal create_fidele
        if fidele.firebase_uid and fidele.firebase_uid != uid:
            return Response({"detail": "Ce compte est lié à un autre identifiant Firebase."}, status=403)
        if not fidele.firebase_uid:
            fidele.firebase_uid = uid
            fidele.save(update_fields=["firebase_uid"])

        # Émettre un JWT pour consommer ton API
        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.pk,
                "email": user.email,
                "phone_number": str(fidele.phone) if fidele.phone else None,
            }
        }, status=200)
class EventCalendarView(StaffRequiredMixin, TemplateView):
    template_name = "event/calendar_view.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Récupération des événements (adapte les filtres selon tes besoins)
        qs = (
            Evenement.objects.select_related("type")
            .order_by("date_debut")
        )

        # Sérialisation FullCalendar
        events = []
        for ev in qs:
            events.append({
                "id": ev.id,
                "title": ev.titre,
                "start": ev.date_debut.isoformat(),
                "end": ev.date_fin.isoformat() if ev.date_fin else None,
                "url": reverse("event-detail", args=[ev.pk]),
                "backgroundColor": self._color_for_type(ev.type.name if ev.type else None),
                "borderColor": self._color_for_type(ev.type.name if ev.type else None),
                "extendedProps": {
                    "lieu": ev.lieu or "",
                    "description": ev.description or "",
                    "banner": ev.banner.url if ev.banner else "",
                    "qr_code": ev.qr_code.url if ev.qr_code else "",
                    "participants": getattr(ev, "nombre_participants", 0),
                },
            })

        # Sérialisé dans le template via |json_script (échappement HTML sûr)
        ctx["events"] = events
        return ctx

    @staticmethod
    def _color_for_type(type_name: str | None) -> str:
        """Mappe un type d’évènement vers une couleur FullCalendar."""
        if not type_name:
            return "#6576ff"  # défaut (DashLite primary)
        key = type_name.strip().lower()
        palette = {
            "meeting": "#6576ff",
            "conférence": "#f56b6b",
            "conference": "#f56b6b",
            "atelier": "#45cb85",
            "workshop": "#45cb85",
            "formation": "#ffaa00",
            "training": "#ffaa00",
            "culte": "#9b51e0",
        }
        return palette.get(key, "#6576ff")


class EventListView(StaffRequiredMixin, ListView):
    model = Evenement
    template_name = "event/eventview.html"
    context_object_name = "ivent"
    paginate_by = 12

    def get_queryset(self):
        qs = super().get_queryset()

        search_query = self.request.GET.get("search") or ""
        if search_query:
            qs = qs.filter(
                Q(titre__icontains=search_query) |
                Q(lieu__icontains=search_query) |
                Q(description__icontains=search_query)
            )

        type_filter = self.request.GET.get("type") or ""
        if type_filter:
            qs = qs.filter(type_id=type_filter)

        status_filter = self.request.GET.get("status") or ""
        now = timezone.now()
        if status_filter == "upcoming":
            qs = qs.filter(date_debut__gt=now)
        elif status_filter == "past":
            qs = qs.filter(date_fin__lt=now)
        elif status_filter == "current":
            qs = qs.filter(date_debut__lte=now, date_fin__gte=now)
        else:
            qs = qs.filter(date_fin__gt=now - timedelta(days=7))

        date_filter = self.request.GET.get("date") or ""
        if date_filter:
            try:
                d = timezone.datetime.strptime(date_filter, "%Y-%m-%d").date()
                qs = qs.filter(date_debut__date__lte=d, date_fin__date__gte=d)
            except ValueError:
                pass

        sort_by = self.request.GET.get("sort") or "date_debut"
        if sort_by in ["date_debut", "date_fin", "titre", "lieu"]:
            qs = qs.order_by(sort_by)

        return qs

    def paginate_queryset(self, queryset, page_size):
        """
        Utilise get_page() → jamais de 404 : renvoie 1ère/dernière page si invalide.
        """
        paginator = self.get_paginator(
            queryset, page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page_number = self.request.GET.get("page")
        page_obj = paginator.get_page(page_number)
        return paginator, page_obj, page_obj.object_list, page_obj.has_other_pages()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Compte total sur le queryset **filtré**
        ctx["nombre_event"] = self.get_queryset().count()

        # Types d’événements pour le filtre
        ctx["event_types"] = TypeEvent.objects.all()

        # Construit un querystring SANS 'page' pour le réinjecter dans les liens de pagination
        qd = self.request.GET.copy()
        qd.pop("page", None)
        ctx["querystring_no_page"] = urlencode(qd)  # ex: "search=...&type=1"
        return ctx
class EventDetailView(StaffRequiredMixin, DetailView):
    model = Evenement
    template_name = "event/event-detail.html"
    context_object_name = "event_detail"

    def get_absolute_url(self):
        return reverse("event-list")

    # --- Actions ---
    def render_qr_pdf(self, event: Evenement) -> HttpResponse:
        if not event.qr_code:
            raise Http404("QR code introuvable.")
        buf = BytesIO()
        # Canvas A4 portrait
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4
        margin = 40

        # Titre
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(HexColor("#111827"))  # gris très foncé
        c.drawString(margin, height - margin - 10, event.titre)

        # Sous-titre (code + date)
        c.setFont("Helvetica", 11)
        c.setFillColor(HexColor("#6B7280"))  # gris
        c.drawString(margin, height - margin - 32, f"Code: {event.code}")
        c.drawString(margin, height - margin - 48, f"Date: {timezone.localtime(event.date_debut).strftime('%d %b %Y • %H:%M')}")

        # QR centré
        qr_img = ImageReader(event.qr_code.path)
        qr_size = min(width, height) * 0.45
        qr_x = (width - qr_size) / 2
        qr_y = (height - qr_size) / 2 - 20
        c.setFillColor(black)
        c.rect(qr_x - 12, qr_y - 12, qr_size + 24, qr_size + 24, stroke=0, fill=1)  # fond noir
        c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size, preserveAspectRatio=True, mask='auto')

        # Footer
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(HexColor("#9CA3AF"))
        c.drawCentredString(width/2, margin, "Présentez ce QR lors du contrôle à l’entrée")

        c.showPage()
        c.save()
        buf.seek(0)
        resp = HttpResponse(buf, content_type="application/pdf")
        resp['Content-Disposition'] = f'attachment; filename="{event.code}_qr.pdf"'
        return resp

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event: Evenement = ctx["event_detail"]

        participants_qs = ParticipationEvenement.objects.filter(evenement=event).select_related("fidele__user")
        nb_participants = participants_qs.count()
        taux = event.taux_participation
        now = timezone.now()

        ctx.update({
            "participants": participants_qs,
            "nb_participants": nb_participants,
            "taux_participation": round(taux, 1) if taux else 0,
            "is_future": event.date_debut > now,
            "is_ongoing": event.date_debut <= now <= event.date_fin,
            "is_past": event.date_fin < now,
            "duration_hours": max(1, int((event.date_fin - event.date_debut).total_seconds() // 3600)),
            "actions": {
                "download_qr_url": f"{self.request.path}?action=download_qr",
                "ics_url": f"{self.request.path}?action=ics",
            }
        })
        return ctx

    def ics_response(self, event: Evenement) -> HttpResponse:
        # Petit ICS minimaliste
        dt_start = timezone.localtime(event.date_debut).strftime('%Y%m%dT%H%M%S')
        dt_end = timezone.localtime(event.date_fin).strftime('%Y%m%dT%H%M%S')
        ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ABMCI//Event//FR
BEGIN:VEVENT
UID:{event.code}@abmci
DTSTAMP:{timezone.now().strftime('%Y%m%dT%H%M%S')}
DTSTART:{dt_start}
DTEND:{dt_end}
SUMMARY:{event.titre}
LOCATION:{event.lieu}
DESCRIPTION:{event.description}
END:VEVENT
END:VCALENDAR
"""
        resp = HttpResponse(ics, content_type="text/calendar; charset=utf-8")
        resp['Content-Disposition'] = f'attachment; filename="{event.code}.ics"'
        return resp

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.GET.get("action")
        if action == "download_qr":
            return self.render_qr_pdf(self.object)
        if action == "ics":
            return self.ics_response(self.object)
        return super().get(request, *args, **kwargs)


class EvenementCreateView(StaffRequiredMixin, CreateView):
    model = Evenement
    template_name = 'event/evenement_create.html'
    form_class = EvenementForm
    success_url = reverse_lazy('event-list')

    def form_valid(self, form):
        # Associer l'église de l'utilisateur connecté
        eglise = None
        if hasattr(self.request.user, "fidele") and getattr(self.request.user.fidele, "eglise_id", None):
            eglise = self.request.user.fidele.eglise
        elif getattr(self.request.user, "eglise_id", None):
            eglise = self.request.user.eglise
        if eglise:
            form.instance.eglise = eglise

        # 1) on crée le parent
        response = super().form_valid(form)

        # 2) si récurrent -> déclenche la génération en arrière-plan
        parent = self.object
        if parent.is_recurrent and parent.recurrence_rule:
            generate_recurrences_task.delay(parent.id)
            messages.success(self.request, "Événement créé. Génération des occurrences en cours…")

        return response

class EvenementUpdateView(StaffRequiredMixin, UpdateView):
    model = Evenement
    template_name = 'event/evenement_create.html'  # evenement_update.html n'existe pas : même formulaire
    fields = ['titre', 'date_debut', 'date_fin', 'lieu', 'description',
              'type', 'banner', 'is_recurrent', 'recurrence_rule', 'end_recurrence']

    def get_success_url(self):
        return reverse_lazy('event-detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        # Si on passe d'un événement non récurrent à récurrent
        original_event = self.get_object()
        was_recurrent = original_event.is_recurrent

        response = super().form_valid(form)

        # Si l'événement est maintenant récurrent, créer les occurrences
        if form.instance.is_recurrent and form.instance.recurrence_rule and not was_recurrent:
            # Même mécanisme que la création : génération idempotente en arrière-plan
            generate_recurrences_task.delay(self.object.id)
            messages.success(self.request, "Événement modifié. Génération des occurrences en cours…")

        return response


class EvenementDeleteView(StaffRequiredMixin, DeleteView):
    model = Evenement
    template_name = 'eden/confirm_delete.html'  # confirmation générique existante
    success_url = reverse_lazy('event-list')

    def form_valid(self, form):
        # Django ≥ 4 : DeleteView passe par form_valid (delete() n'est plus appelée sur POST)
        messages.success(self.request, f"L'événement '{self.object.titre}' a été supprimé.")
        return super().form_valid(form)


# Vue pour gérer les occurrences d'un événement récurrent
class EvenementOccurrencesView(StaffRequiredMixin, DetailView):
    model = Evenement
    template_name = 'evenement_occurrences.html'
    context_object_name = 'event'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.is_recurrent:
            # Occurrences réellement enregistrées (generate_events() n'existait pas)
            context['occurrences'] = self.object.children.order_by('date_debut')
        return context