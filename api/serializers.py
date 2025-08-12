from dj_rest_auth.registration.serializers import RegisterSerializer
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance, D
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from phonenumber_field.formfields import PhoneNumberField
from phonenumber_field.phonenumber import to_python
from rest_framework import serializers
from django.contrib.auth import get_user_model

from event.models import ParticipationEvenement
from fidele.models import Fidele, UserProfileCompletion, Eglise, SEXE_CHOICES, MARITAL_CHOICES, Location, FidelePosition
from phonenumber_field.serializerfields import PhoneNumberField as DRFPhoneNumberField

# from .models import Fidele, UserProfileCompletion

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name']


class PositionInputSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy = serializers.DecimalField(max_digits=7, decimal_places=2, required=False, allow_null=True)
    captured_at = serializers.DateTimeField(required=False, allow_null=True)
    source = serializers.ChoiceField(
        choices=FidelePosition.SOURCES if hasattr(FidelePosition, "SOURCES") else (("manual", "Manual"),),
        required=False, allow_null=True
    )
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        lat, lng = float(attrs["latitude"]), float(attrs["longitude"])
        if not (-90 <= lat <= 90):
            raise ValidationError("Latitude hors bornes (-90..90).")
        if not (-180 <= lng <= 180):
            raise ValidationError("Longitude hors bornes (-180..180).")
        return attrs


def _parse_float(v):
    try:
        return float(v)
    except Exception:
        return None


def get_point_from_request(request):
    """
    Récupère au mieux la position user *sans champs exposés* :
    1) Headers (envoyés par le front/app) :
       X-Geo-Lat, X-Geo-Lng
       X-Geo-Accuracy (optionnel)
    2) (Optionnel) GeoIP à partir de l’adresse IP si headers absents.
    Retourne (Point|None, accuracy|None, source:str)
    """
    # 1) Headers passés par le client (recommandé)
    lat = _parse_float(request.headers.get("X-Geo-Lat"))
    lng = _parse_float(request.headers.get("X-Geo-Lng"))
    acc = _parse_float(request.headers.get("X-Geo-Accuracy"))
    if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
        return Point(lng, lat, srid=4326), acc, "client_header"

    # 2) (Optionnel) GeoIP d’après IP (précision très approximative)
    # Nécessite GeoIP2 + base mmdb et config GEOIP_PATH dans settings
    try:
        from django.contrib.gis.geoip2 import GeoIP2
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
        if ip:
            g = GeoIP2()
            city = g.city(ip)  # {'latitude':..., 'longitude':...}
            if city and "latitude" in city and "longitude" in city:
                return Point(city["longitude"], city["latitude"], srid=4326), None, "geoip"
    except Exception:
        pass

    return None, None, "none"


class CustomRegisterSerializer(RegisterSerializer):
    # Identité
    first_name = serializers.CharField(required=True, max_length=50)
    last_name  = serializers.CharField(required=True, max_length=150)
    phone      = DRFPhoneNumberField(region='CI', required=False, allow_null=True)
    birthdate  = serializers.DateField(required=True)

    # Champs fidèles
    sexe = serializers.ChoiceField(choices=SEXE_CHOICES, required=False, allow_null=True)
    situation_matrimoniale = serializers.ChoiceField(choices=MARITAL_CHOICES, required=False, allow_null=True)

    # Église explicitement fournie (facultatif — si absente on déduit)
    eglise = serializers.PrimaryKeyRelatedField(queryset=Eglise.objects.all(), required=False, allow_null=True)

    NEARBY_RADIUS_KM = 10  # rayon de recherche

    def validate_birthdate(self, value):
        if value > timezone.now().date():
            raise ValidationError("La date de naissance ne peut pas être dans le futur.")
        return value

    def get_cleaned_data(self):
        cleaned = super().get_cleaned_data()
        vd = self.validated_data
        cleaned.update({
            "first_name": vd.get("first_name", "").strip(),
            "last_name":  vd.get("last_name", "").strip(),
            "phone":      vd.get("phone"),
            "birthdate":  vd.get("birthdate"),
            "sexe":       vd.get("sexe"),
            "situation_matrimoniale": vd.get("situation_matrimoniale"),
            "eglise":     vd.get("eglise"),  # peut rester None → auto
        })
        return cleaned

    def _find_nearest_eglise(self, point):
        if point is None:
            return None
        qs = (Eglise.objects
              .exclude(location__isnull=True)
              .filter(location__distance_lte=(point, D(km=self.NEARBY_RADIUS_KM)))
              .annotate(distance=Distance("location", point))
              .order_by("distance"))
        return qs.first()

    @transaction.atomic
    def save(self, request):
        # Création user (allauth)
        user = super().save(request)
        data = self.get_cleaned_data()

        # Maj nom/prénom
        user.first_name = data["first_name"]
        user.last_name  = data["last_name"]
        user.save(update_fields=["first_name", "last_name"])

        # Récupérer position depuis request (headers/geoip), hors schéma public
        point, accuracy, source = get_point_from_request(request)

        # Déterminer l’église si non fournie
        selected_eglise = data.get("eglise") or self._find_nearest_eglise(point)

        # (Option) si aucune église → lever une erreur
        # if selected_eglise is None:
        #     raise ValidationError("Impossible de déterminer l'église (aucune position proche).")

        default_location = Location.objects.filter(pk=1).first()

        fidele, _ = Fidele.objects.update_or_create(
            user=user,
            defaults={
                "phone":      data.get("phone") or None,
                "birthdate":  data.get("birthdate"),
                "eglise":     selected_eglise,
                "date_entree": timezone.now().date(),
                "sexe":       data.get("sexe"),
                "situation_matrimoniale": data.get("situation_matrimoniale"),
                "location":   default_location,
                "membre":     0,
                "sortie":     0,
                "is_deleted": 0,
            },
        )

        # Historiser la position captée (si on en a une)
        if point is not None:
            FidelePosition.objects.create(
                fidele=fidele,
                latitude=point.y,   # si tu as DecimalFields lat/lng
                longitude=point.x,
                accuracy=accuracy,
                source=source,
                captured_at=timezone.now(),
            )

        return user

class CustomUserDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name']
        read_only_fields = ('email',)


class FideleSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    age = serializers.SerializerMethodField()
    statut = serializers.SerializerMethodField()
    anciennete = serializers.SerializerMethodField()

    class Meta:
        model = Fidele
        fields = '__all__'
        depth = 1

    def get_age(self, obj):
        return obj.age()

    def get_statut(self, obj):
        return obj.statut

    def get_anciennete(self, obj):
        return obj.anciennete


class FideleCreateUpdateSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(write_only=True)
    last_name = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = Fidele
        exclude = ['user', 'qlook_id', 'slug', 'created_at']

    def create(self, validated_data):
        user_data = {
            'email': validated_data.pop('email'),
            'first_name': validated_data.pop('first_name'),
            'last_name': validated_data.pop('last_name'),
            'password': validated_data.pop('password'),
        }

        user = User.objects.create_user(
            email=user_data['email'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            password=user_data['password']
        )

        fidele = Fidele.objects.create(user=user, **validated_data)
        return fidele


class UserProfileCompletionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfileCompletion
        fields = '__all__'


class ParticipationEvenementSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParticipationEvenement
        fields = ['id', 'fidele', 'evenement', 'commentaire', 'date', 'qr_code_scanned']
        read_only_fields = ['date', 'qr_code_scanned']

    def validate(self, data):
        # Vérifier si l'événement n'est pas encore arrivé
        if data['evenement'].date_debut > timezone.now():
            raise serializers.ValidationError("Cet événement n'a pas encore commencé.")

        # Vérifier si l'utilisateur a déjà scanné ce QR code
        if ParticipationEvenement.objects.filter(
                fidele=data['fidele'],
                evenement=data['evenement']
        ).exists():
            raise serializers.ValidationError("Vous avez déjà scanné ce QR code.")

        return data
