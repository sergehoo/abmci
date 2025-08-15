from __future__ import annotations

import json
from datetime import timedelta, datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect
from django.views.generic import ListView, DetailView, TemplateView
from django.views.generic.edit import CreateView
from django.urls import reverse_lazy, reverse
from django.utils import timezone
import qrcode
from PIL import Image
from io import BytesIO

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from event.models import Evenement, ParticipationEvenement
from reportlab.pdfgen import canvas
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework_simplejwt.tokens import RefreshToken
from firebase_admin import auth as fb_auth, _auth_utils
import phonenumbers

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
            decoded = fb_auth.verify_id_token(id_token)
        except _auth_utils.InvalidIdTokenError:
            return Response({"detail": "ID token invalide."}, status=401)
        except _auth_utils.ExpiredIdTokenError:
            return Response({"detail": "ID token expiré."}, status=401)
        except Exception as e:
            return Response({"detail": f"Vérification échouée: {e}"}, status=401)

        uid = decoded.get("uid")
        email = decoded.get("email")
        email_verified = decoded.get("email_verified", False)
        phone = normalize_phone(decoded.get("phone_number"))
        provider = decoded.get("firebase", {}).get("sign_in_provider")  # 'password' | 'phone' | 'google.com'...

        if not uid:
            return Response({"detail": "UID Firebase manquant."}, status=400)

        # Reconciliation
        user = None
        # 1) par firebase_uid
        try:
            user = User.objects.get(firebase_uid=uid)
        except User.DoesNotExist:
            pass
        # 2) par email
        if user is None and email:
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                pass
        # 3) par phone
        if user is None and phone:
            try:
                user = User.objects.get(phone_number=phone)
            except User.DoesNotExist:
                pass
        # 4) créer sinon
        if user is None:
            username = email or f"user_{uid[:8]}"
            user = User.objects.create(
                username=username,
                email=email or "",
                firebase_uid=uid,
                phone_number=phone,
                is_active=True,
            )
        else:
            changed = False
            if not getattr(user, "firebase_uid", None):
                user.firebase_uid = uid; changed = True
            if email and user.email != email:
                user.email = email; changed = True
            if phone and getattr(user, "phone_number", None) != phone:
                user.phone_number = phone; changed = True
            if changed:
                user.save(update_fields=["firebase_uid","email","phone_number"])

        # Politique : pour provider "password", refuser si e-mail non vérifié
        if provider == "password" and email and not email_verified:
            return Response({"detail": "E-mail non vérifié."}, status=403)

        # Émettre un JWT pour consommer ton API
        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.pk,
                "email": user.email,
                "phone_number": getattr(user, "phone_number", None),
            }
        }, status=200)
class EventCalendarView(TemplateView):
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

        ctx["events_json"] = json.dumps(events, cls=DjangoJSONEncoder)
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


class EventListView(LoginRequiredMixin, ListView):
    model = Evenement
    template_name = "event/eventview.html"
    context_object_name = 'ivent'

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(date_debut__gt=timezone.now() - timedelta(days=7))
        return queryset

    # def get_queryset(self):
    #     # Filtrer les événements dont la date de fin est ultérieure à la date actuelle
    #     return Evenement.objects.filter(date_fin__gt=timezone.now())

    # def get_queryset(self):
    #     # Calculer la date actuelle
    #     current_date = timezone.now()
    #
    #     # Calculer la date dans 7 jours
    #     seven_days_later = current_date + timedelta(days=7)
    #
    #     # Filtrer les événements dont la date de fin est dans les 7 jours suivants
    #     return Evenement.objects.filter(date_fin__gt=current_date, date_fin__lte=seven_days_later)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer le nombre total de membres
        context['nombre_event'] = Evenement.objects.count()

        return context


class EventDetailView(LoginRequiredMixin, DetailView):
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


class EvenementCreateView(CreateView):
    model = Evenement
    template_name = 'evenement_create.html'
    fields = ['titre', 'date_debut', 'date_fin', 'lieu', 'description', 'type', 'banner', 'qr_code']
    success_url = reverse_lazy('evenement_list')

    # def form_valid(self, form):
    #     # Appel à la méthode form_valid de la classe parente pour enregistrer le modèle
    #     response = super().form_valid(form)
    #
    #     # Génération du code QR
    #     data = f'Event: {self.object.titre}, Date: {self.object.date_debut}'
    #     qr_code_data = generate_qr_code(data)
    #
    #     # Enregistrement du code QR dans l'objet Evenement
    #     self.object.qr_code.save('qrcode.png', ContentFile(qr_code_data), save=True)
    #
    #     return response
