from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from allauth.account.models import EmailAddress
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework.views import APIView

from api.serializers import UserSerializer, FideleSerializer, FideleCreateUpdateSerializer, \
    UserProfileCompletionSerializer, ParticipationEvenementSerializer, VerseDuJourSerializer
from event.models import ParticipationEvenement, Evenement
from fidele.models import Fidele, UserProfileCompletion, Eglise

# from .models import Fidele, UserProfileCompletion
# from .serializers import (
#     UserSerializer,
#     FideleSerializer,
#     FideleCreateUpdateSerializer,
#     UserProfileCompletionSerializer
# )

User = get_user_model()

schema_view = get_schema_view(
    openapi.Info(
        title="API Documentation",
        default_version='v1',
        description="API for mobile application",
    ),
    public=True,
)


class UserDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class FideleListView(generics.ListAPIView):
    queryset = Fidele.objects.all()
    serializer_class = FideleSerializer
    permission_classes = [permissions.IsAuthenticated]


class FideleDetailView(generics.RetrieveUpdateAPIView):
    queryset = Fidele.objects.all()
    serializer_class = FideleSerializer
    permission_classes = [permissions.IsAuthenticated]


class FideleCreateView(generics.CreateAPIView):
    queryset = Fidele.objects.all()
    serializer_class = FideleCreateUpdateSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        fidele = serializer.save()
        # Créer un profil de complétion pour le nouvel utilisateur
        UserProfileCompletion.objects.create(user=fidele.user)


class ProfileCompletionView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileCompletionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        user = self.request.user
        profile, created = UserProfileCompletion.objects.get_or_create(user=user)
        return profile


class VerifyEmailView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        key = kwargs.get('key')
        email = EmailAddress.objects.filter(key=key).first()

        if email:
            email.verified = True
            email.save()
            return Response({'detail': 'Email vérifié avec succès.'}, status=status.HTTP_200_OK)
        return Response({'detail': 'Lien de vérification invalide.'}, status=status.HTTP_400_BAD_REQUEST)


def _verify_signed_qr(payload_b64: str) -> str | None:
    """
    FACULTATIF : si vous décidez d’encoder dans le QR un payload signé plutôt que le simple code.
    Le QR contiendrait par ex. base64url({"code":"EVT123","exp":1699999999,"sig":<hmac>})
    Retourne event_code si signature OK et non expiré, sinon None.
    """
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + '=' * (-len(payload_b64) % 4))
        data = json.loads(raw.decode('utf-8'))
        msg = f"{data['code']}.{data['exp']}".encode('utf-8')
        sig = base64.urlsafe_b64decode(data['sig'] + '=' * (-len(data['sig']) % 4))
        expected = hmac.new(settings.SECRET_KEY.encode('utf-8'), msg, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        if timezone.now().timestamp() > float(data['exp']):
            return None
        return data['code']
    except Exception:
        return None


class ScanQRCodeAPIView(APIView):
    """
    POST /api/scan-qr/<event_code>/
    (ou POST avec body={"qr":"<payload_b64>"} si vous utilisez la variante signée)
    - QR actif : [start - 15min, end + 6h]
    - idempotent : renvoie 200 si déjà présent
    - throttle scope : qr-scan
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'qr-scan'

    # Fenêtres (ajustez si besoin)
    ALLOW_BEFORE_MIN = 15
    ALLOW_AFTER_MIN = 6 * 60

    def post(self, request, event_code=None):
        # Variante SIGNÉE (décommentez pour l’utiliser côté app mobile et ici)
        # if 'qr' in request.data:
        #     decoded_code = _verify_signed_qr(request.data['qr'])
        #     if not decoded_code:
        #         return Response({"detail": "QR invalide ou expiré."}, status=400)
        #     event_code = decoded_code

        evenement = get_object_or_404(Evenement, code=event_code)
        fidele = get_object_or_404(Fidele, user=request.user)

        now = timezone.now()
        start = evenement.date_debut
        end = evenement.date_fin

        # Un QR dont la date n’est pas encore arrivée ne peut pas être scanné
        if now < (start - timedelta(minutes=self.ALLOW_BEFORE_MIN)):
            return Response(
                {"detail": "Le QR code n’est pas encore actif."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Optionnel : interdiction après fin + marge
        if now > (end + timedelta(minutes=self.ALLOW_AFTER_MIN)):
            return Response(
                {"detail": "Le QR code a expiré."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                participation, created = ParticipationEvenement.objects.get_or_create(
                    fidele=fidele,
                    evenement=evenement,
                    defaults={'qr_code_scanned': True}
                )

                if created:
                    # ➜ Ici, abonnez l’utilisateur aux notifications de l’évènement si besoin
                    self._schedule_pre_event_notifications(evenement, fidele)
                    serializer = ParticipationEvenementSerializer(participation, context={'request': request})
                    return Response(serializer.data, status=status.HTTP_201_CREATED)

                # Idempotent : déjà enregistré → 200
                return Response({"detail": "Présence déjà enregistrée."}, status=status.HTTP_200_OK)

        except IntegrityError:
            # Contrainte unique_together : déjà enregistré
            return Response({"detail": "Présence déjà enregistrée."}, status=status.HTTP_200_OK)

    def _schedule_pre_event_notifications(self, evenement: Evenement, fidele: Fidele):
        """
        Hook pour planifier des notifications (24h / 3h / 30min avant).
        Implémentez avec Celery/Beat, django-q, APScheduler, etc.
        Exemple (Celery) :
            from .tasks import notify_one
            for delta in [timedelta(hours=24), timedelta(hours=3), timedelta(minutes=30)]:
                eta = evenement.date_debut - delta
                if eta > timezone.now():
                    notify_one.apply_async(kwargs={'fidele_id': fidele.id, 'event_id': evenement.id}, eta=eta)
        """
        pass


class ParticipationListCreateView(generics.ListCreateAPIView):
    """
    GET /api/participations/  : liste des participations de l’utilisateur
    POST /api/participations/ : crée une participation (cas administratif si besoin)
    """
    serializer_class = ParticipationEvenementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        fidele = get_object_or_404(Fidele, user=self.request.user)
        return (ParticipationEvenement.objects
                .filter(fidele=fidele)
                .select_related('evenement')
                .order_by('-date'))

    def perform_create(self, serializer):
        fidele = get_object_or_404(Fidele, user=self.request.user)
        serializer.save(fidele=fidele, qr_code_scanned=True)


class VerseDuJourView(generics.RetrieveAPIView):
    serializer_class = VerseDuJourSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Église du fidèle connecté
        fidele = getattr(self.request.user, 'fidele', None)
        if not fidele or not fidele.eglise_id:
            # Laisse DRF renvoyer 404 proprement
            raise get_object_or_404(Eglise, pk=-1)  # forcera 404
        return get_object_or_404(Eglise, pk=fidele.eglise_id)