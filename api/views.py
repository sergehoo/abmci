from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction, models
from django.db.models import Q, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import http_date
from django.utils.timezone import now
from rest_framework import generics, permissions, status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from allauth.account.models import EmailAddress
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework.views import APIView

from api.serializers import UserSerializer, FideleSerializer, FideleCreateUpdateSerializer, \
    UserProfileCompletionSerializer, ParticipationEvenementSerializer, VerseDuJourSerializer, EvenementListSerializer, \
    PrayerCommentSerializer, PrayerCategorySerializer, PrayerRequestSerializer, NotificationSerializer, \
    DeviceSerializer, BibleVersionSerializer, BibleVerseSerializer, BibleTagCreateSerializer, BannerSerializer
from event.models import ParticipationEvenement, Evenement
from fidele.models import Fidele, UserProfileCompletion, Eglise, PrayerComment, PrayerRequest, PrayerLike, \
    PrayerCategory, Notification, Device, BibleVersion, BibleVerse, BibleTag, Banner

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


DEFAULT_HORIZON_DAYS = 60


class UpcomingEventsView(generics.ListAPIView):
    serializer_class = EvenementListSerializer
    permission_classes = [permissions.IsAuthenticated]  # on filtre par l’église du fidèle

    def get_queryset(self):
        user = self.request.user
        fidele = getattr(user, "fidele", None)

        if not fidele or not fidele.eglise_id:
            raise ValidationError("Aucune église associée à l'utilisateur.")

        now = timezone.now()
        days = int(self.request.query_params.get("days", DEFAULT_HORIZON_DAYS))
        until = now + timezone.timedelta(days=days)

        qs = (
            Evenement.objects.select_related("eglise", "type")
            .filter(
                eglise_id=fidele.eglise_id,
                date_fin__gte=now,  # pas encore fini
                date_debut__lte=until,  # dans l’horizon
            )
            .order_by("date_debut", "id")
        )

        # Filtres optionnels
        type_id = self.request.query_params.get("type_id")
        if type_id:
            qs = qs.filter(type_id=type_id)

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(titre__icontains=q) | Q(lieu__icontains=q))

        return qs


class UpcomingEventsHomeView(UpcomingEventsView):
    """Version allégée pour l’accueil — renvoie les N prochains (3 par défaut)."""

    def list(self, request, *args, **kwargs):
        limit = int(request.query_params.get("limit", 3))
        self.pagination_class = None  # pas de pagination, on limite directement
        queryset = self.filter_queryset(self.get_queryset())[:limit]
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS: return True
        return getattr(obj, 'user_id', None) == request.user.id


class PrayerCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PrayerCategory.objects.all()
    serializer_class = PrayerCategorySerializer
    permission_classes = [permissions.AllowAny]


class PrayerRequestViewSet(viewsets.ModelViewSet):
    serializer_class = PrayerRequestSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]  # pour audio

    def get_queryset(self):
        # Chargement optimal des relations
        qs = PrayerRequest.objects.select_related('user', 'category') \
            .prefetch_related(
            'likes',
            Prefetch('comments',
                     queryset=PrayerComment.objects.select_related('user')
                     .only('id', 'content', 'created_at', 'user_id', 'prayer_id')
                     )
        )

        # Filtres
        t = self.request.query_params.get('type')
        q = self.request.query_params.get('q')
        if t in {'PR', 'EX', 'IN'}:
            qs = qs.filter(prayer_type=t)
        if q:
            qs = qs.filter(
                models.Q(title__icontains=q) |
                models.Q(content__icontains=q)
            )
        return qs.order_by('-created_at')

    # action comments
    @action(
        detail=True, methods=['get', 'post'],
        permission_classes=[permissions.IsAuthenticatedOrReadOnly],
        parser_classes=[JSONParser, FormParser, MultiPartParser],
    )
    def comments(self, request, pk=None):
        prayer = self.get_object()

        if request.method == 'GET':
            qs = (PrayerComment.objects
                  .filter(prayer_id=prayer.id)
                  .select_related('user')
                  .order_by('created_at'))
            data = PrayerCommentSerializer(qs, many=True).data
            return Response(data)

        # POST
        ser = PrayerCommentSerializer(data=request.data)
        if not ser.is_valid():
            # LOG + réponse explicite
            print('comment validation errors:', ser.errors)  # ou logger.warning(...)
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        ser.save(prayer=prayer, user=request.user)
        return Response(ser.data, status=status.HTTP_201_CREATED)
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        prayer = self.get_object()
        like, created = PrayerLike.objects.get_or_create(prayer=prayer, user=request.user)
        if not created:
            like.delete()
            return Response({
                'status': 'unliked',
                'likes_count': prayer.likes.count(),
                'has_liked': False
            }, status=200)
        return Response({
            'status': 'liked',
            'likes_count': prayer.likes.count(),
            'has_liked': True
        }, status=201)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx


class PrayerCommentViewSet(viewsets.ModelViewSet):
    serializer_class = PrayerCommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        return PrayerComment.objects.filter(user=self.request.user).select_related('user', 'prayer')

    def perform_create(self, serializer):
        prayer = get_object_or_404(PrayerRequest, pk=self.request.data.get('prayer'))
        serializer.save(user=self.request.user, prayer=prayer)

class DeviceViewSet(viewsets.ModelViewSet):
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Device.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        # upsert par token
        instance, _ = Device.objects.update_or_create(
            token=serializer.validated_data['token'],
            defaults={
                'user': self.request.user,
                'platform': serializer.validated_data.get('platform', 'android')
            }
        )
        self.instance = instance

    def create(self, request, *args, **kwargs):
        resp = super().create(request, *args, **kwargs)
        return resp

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by('-created_at')

class BibleVersionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = BibleVersion.objects.all()
    serializer_class = BibleVersionSerializer
    permission_classes = [permissions.AllowAny]

    @action(detail=True, methods=["get"], url_path="verses")
    def verses(self, request, pk=None):
        """/bible/versions/<id>/verses/?updated_after=ISO8601&page=1"""
        version = self.get_object()
        qs = BibleVerse.objects.filter(version=version)

        ua = request.query_params.get("updated_after")
        if ua:
            dt = parse_datetime(ua)
            if dt:
                qs = qs.filter(updated_at__gt=dt)

        # filtres optionnels pour des téléchargements ciblés
        b = request.query_params.get("book")
        if b: qs = qs.filter(book=b)
        ch = request.query_params.get("chapter")
        if ch: qs = qs.filter(chapter=int(ch))

        qs = qs.order_by("book", "chapter", "verse")

        page = self.paginate_queryset(qs)
        ser = BibleVerseSerializer(page, many=True)
        return self.get_paginated_response(ser.data)

    def get_queryset(self):
        return BibleVersion.objects.all().order_by('code')

class BibleVerseViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = BibleVerse.objects.all().select_related("version")
    serializer_class = BibleVerseSerializer
    pagination_class = PageNumberPagination
    permission_classes = [permissions.AllowAny]

    def list(self, request, *args, **kwargs):
        """Endpoint global optionnel: /bible/verses/?version=LSG&updated_after=..."""
        qs = self.get_queryset()
        v = request.query_params.get("version")
        if v: qs = qs.filter(version__code=v)
        ua = request.query_params.get("updated_after")
        if ua:
            dt = parse_datetime(ua)
            if dt:
                qs = qs.filter(updated_at__gt=dt)
        b = request.query_params.get("book")
        if b: qs = qs.filter(book=b)
        ch = request.query_params.get("chapter")
        if ch: qs = qs.filter(chapter=int(ch))

        qs = qs.order_by("book", "chapter", "verse")
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page, many=True)
        return self.get_paginated_response(ser.data)


class BibleTagViewSet(viewsets.GenericViewSet):
    queryset = BibleTag.objects.select_related('sender', 'recipient')
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return BibleTagCreateSerializer

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data, context={'request': request})
        ser.is_valid(raise_exception=True)
        tag = ser.save()
        return Response({'id': tag.id}, status=status.HTTP_201_CREATED)

class BannerPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100

class BannerListView(generics.ListAPIView):
    """
    GET /api/banners/?active=true|false (par défaut true)
    Query params: limit, offset (pagination)
    Renvoie ETag + Cache-Control.
    """
    serializer_class = BannerSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = BannerPagination

    def get_queryset(self):
        qs = Banner.objects.all()
        active_param = self.request.query_params.get("active", "true").lower()
        if active_param in ("1", "true", "yes"):
            qs = qs.filter(active=True)
        return qs.order_by("order", "-updated_at")

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()

        # ETag basé sur le max(updated_at) + count
        last_upd = qs.order_by("-updated_at").values_list("updated_at", flat=True).first()
        count = qs.count()
        base = f"{last_upd.isoformat() if last_upd else 'none'}:{count}"
        etag = hashlib.md5(base.encode("utf-8")).hexdigest()

        # Gestion If-None-Match -> 304 si identique
        if_none_match = request.META.get("HTTP_IF_NONE_MATCH")
        if if_none_match and if_none_match.strip('"') == etag:
            resp = Response(status=304)
            resp["ETag"] = f'"{etag}"'
            resp["Cache-Control"] = "public, max-age=60"  # 1 min côté client
            return resp

        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page, many=True, context={"request": request})
        resp = self.get_paginated_response(serializer.data)

        # Entêtes cache
        resp["ETag"] = f'"{etag}"'
        resp["Cache-Control"] = "public, max-age=60"
        resp["Last-Modified"] = http_date((last_upd or now()).timestamp())
        return resp