from django.utils import timezone
from rest_framework import serializers
from django.contrib.auth import get_user_model

from event.models import ParticipationEvenement
from fidele.models import Fidele, UserProfileCompletion

# from .models import Fidele, UserProfileCompletion

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name']


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