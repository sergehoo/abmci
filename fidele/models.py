import random
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import now
from simple_history.models import HistoricalRecords
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from django.contrib.gis.db import models as gis_models

# Create your models here.

MARITAL_CHOICES = [
    ('MARIE', 'MARIE'),
    ('CELIBATAIRE', 'CELIBATAIRE'),
    ('CONCUBINAGE', 'CONCUBINAGE'),
    ('UNION LIBRE', 'UNION LIBRE'),
    ('VEUF ', 'VEUF'),
]

SEXE_CHOICES = [
    ('Homme', 'Homme'),
    ('Femme', 'Femme')
]

CONTRY_CHOICES = [
    ('Côte d\'Ivoire', 'Côte d\'Ivoire'),
    ('France', 'France'),
    ('Congo', 'Congo'),
]

BAPTEME_CHOICES = [
    ('Immersion', 'Immersion'),
    ('Aspersion', 'Aspersion'),
]


def qlook():
    qlook = ("QL" + str(random.randrange(0, 999999999, 1)) + "AB")
    return qlook

class Device(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='devices')
    token = models.CharField(max_length=255, unique=True)  # FCM token
    platform = models.CharField(max_length=20, choices=[('android','Android'), ('ios','iOS')])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(auto_now=True)

class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=140)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)  # deep-link payload (type, ids, etc)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
class Fonction(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return f'{self.name}'


class Permanence(models.Model):
    from event.models import Evenement
    titre = models.CharField(max_length=150, blank=True, null=True)
    event = models.ForeignKey(Evenement, on_delete=models.CASCADE, blank=True, null=True)
    auteur = models.ForeignKey('Fidele', related_name="auteur", on_delete=models.CASCADE, blank=True, null=True)
    direction = models.ForeignKey('Department', on_delete=models.CASCADE, blank=True, null=True)
    add_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.titre} {self.event}'


class OuvrierPermanence(models.Model):
    ouvrier = models.ForeignKey('Fidele', on_delete=models.CASCADE, blank=True, null=True)
    poste = models.ForeignKey(Fonction, on_delete=models.CASCADE, blank=True, null=True)
    position = models.CharField(max_length=200, blank=True, null=True)
    activites = models.CharField(max_length=500, blank=True, null=True)
    add_date = models.DateTimeField(auto_now_add=True)
    date = models.DateTimeField(blank=True, null=True)
    programme = models.ForeignKey(Permanence, blank=True, null=True, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.ouvrier} {self.programme}'


class Department(models.Model):
    name = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    responsable = models.ForeignKey('fidele', related_name="responsable", on_delete=models.CASCADE, blank=True,
                                    null=True)

    def __str__(self):
        return self.name

    @property
    def members(self):
        # Retrieve and return the members associated with this department
        membre = Fidele.objects.filter(departement=self)
        return membre


class MembreType(models.Model):
    name = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    duree = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return self.name


class TypeLocation(models.Model):
    name = models.CharField(max_length=200, default='ville', blank=True)

    def __str__(self):
        return self.name


class Location(models.Model):
    name = models.CharField(null=True, blank=True, max_length=150, )
    type = models.ForeignKey(TypeLocation, on_delete=models.CASCADE, default=1, null=True, blank=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, default=None, null=True, blank=True)

    def get_all_parents(self):
        parents = []
        current_parent = self.parent

        while current_parent:
            parents.append(current_parent)
            current_parent = current_parent.parent

        return parents

    def __str__(self):
        return self.name


class Eglise(models.Model):
    name = models.CharField(max_length=250, null=True, blank=True)
    ville = models.CharField(max_length=250, null=True, blank=True)
    pasteur = models.CharField(max_length=250, null=True, blank=True)

    # 📍 géométrie: SRID=4326 (WGS84), ordres (lon, lat) !
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    verse_du_jour = models.TextField(null=True, blank=True)
    verse_reference = models.CharField(max_length=100, null=True, blank=True)
    verse_date = models.DateField(default=timezone.now)

    def save(self, *args, **kwargs):
        # Mettre à jour la date seulement si le verset change
        if self.pk and 'verse_du_jour' in kwargs.get('update_fields', []):
            self.verse_date = timezone.now().date()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name or "Église sans nom"


class ProblemeParticulier(models.Model):
    class Gravite(models.TextChoices):
        FAIBLE = 'F', 'Faible'
        MOYEN = 'M', 'Moyen'
        ELEVE = 'E', 'Élevé'
        CRITIQUE = 'C', 'Critique'

    fidele = models.ForeignKey('Fidele', on_delete=models.CASCADE, related_name='problemes')
    type_probleme = models.CharField(max_length=100)
    description = models.TextField()
    date_decouverte = models.DateField()
    gravite = models.CharField(max_length=1, choices=Gravite.choices, default=Gravite.MOYEN)
    statut = models.CharField(max_length=20, default='En cours')
    responsable = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    solution = models.TextField(blank=True)
    date_resolution = models.DateField(null=True, blank=True)


class SujetPriere(models.Model):
    titre = models.CharField(null=True, blank=True, max_length=250)
    descriptif = models.TextField(null=True, blank=True)
    fidele = models.ForeignKey('Fidele', on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True, null=True, blank=True, )
    traitement = models.BooleanField(default=False, null=True, blank=True)

    def __str__(self):
        return self.titre


class Familles(models.Model):
    name = models.CharField(null=True, blank=True, max_length=250)
    mission = models.ForeignKey(Eglise, on_delete=models.CASCADE, null=True, blank=True, max_length=250)

    def __str__(self):
        return self.name


class Fidele(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="fidele", )
    firebase_uid = models.CharField(max_length=128, unique=True, null=True, blank=True)
    qlook_id = models.CharField(default=qlook, unique=True, editable=False, max_length=100)
    birthdate = models.DateField(null=True, blank=True)
    sexe = models.CharField(choices=SEXE_CHOICES, max_length=100, null=True, blank=True, )
    situation_matrimoniale = models.CharField(choices=MARITAL_CHOICES, max_length=100, null=True, blank=True, )
    signe = models.TextField(max_length=500, null=True, blank=True)
    nbr_enfants = models.IntegerField(null=True, blank=True)
    contry = CountryField(blank_label='(Choisissez un pays)', null=True, blank=True)
    phone = PhoneNumberField(region='CI', null=True, blank=True)
    nationalite = models.CharField(null=True, blank=True, max_length=70, )
    eglise_origine = models.CharField(null=True, blank=True, max_length=270)
    date_entree = models.DateField(null=True, blank=True)
    date_bapteme = models.DateField(null=True, blank=True)
    type_bapteme = models.CharField(choices=BAPTEME_CHOICES, max_length=100, null=True, blank=True, )
    lieu_bapteme = models.CharField(max_length=100, null=True, blank=True, )
    profession = models.CharField(null=True, blank=True, max_length=270)
    entreprise = models.CharField(null=True, blank=True, max_length=270)
    mensual_revenue = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True, )
    salary_currency = models.CharField(null=True, blank=True, max_length=20)

    marie_a = models.ForeignKey('self', on_delete=models.CASCADE, related_name='partenair', blank=True, null=True)
    pere = models.ForeignKey('self', on_delete=models.CASCADE, related_name='paternelle', blank=True, null=True)
    mere = models.ForeignKey('self', on_delete=models.CASCADE, related_name='maternelle', blank=True, null=True)
    frere = models.ManyToManyField('self', blank=True, symmetrical=True)
    soeur = models.ManyToManyField('self', blank=True, symmetrical=True)

    type_membre = models.ForeignKey('MembreType', on_delete=models.CASCADE, blank=True, null=True)
    membre = models.SmallIntegerField(blank=True, null=True, default=0)
    location = models.ForeignKey(Location, on_delete=models.CASCADE, default=1, blank=True)
    departement = models.ForeignKey('Department', on_delete=models.CASCADE, blank=True, null=True)
    fonction = models.ForeignKey('Fonction', on_delete=models.CASCADE, blank=True, null=True)
    eglise = models.ForeignKey('Eglise', on_delete=models.CASCADE, null=True, blank=True)
    famille_alliance = models.ForeignKey('Familles', on_delete=models.CASCADE, null=True, blank=True)

    photo = models.ImageField(null=True, blank=True, default='abmci/users/7.png', upload_to='abmci/fideles')
    sortie = models.SmallIntegerField(null=True, blank=True, default=0)
    is_deleted = models.SmallIntegerField(null=True, blank=True, default=0)
    slug = models.SlugField(null=True, blank=True, help_text="slug field", verbose_name="slug ", unique=True,
                            editable=False)
    created_at = models.DateTimeField(auto_now_add=now, )
    history = HistoricalRecords()

    def __str__(self):
        return f'{self.user.first_name} {self.user.last_name}'

    def save(self, *args, **kwargs):
        # self.age = (date.today() - self.date_naissance) // (timedelta(days=365.2425))
        self.slug = slugify(self.qlook_id)
        super(Fidele, self).save(*args, **kwargs)

    class Meta:
        permissions = (
            ("can_edit_employee", "Can edit employee"),
        )

    @property
    def est_nouveau(self):
        # Calcule la différence entre la date d'entrée et la date actuelle
        difference = timezone.now().date() - self.date_entree

        # Vérifie si la différence est inférieure à 3 mois
        if difference.days < 90:
            return True
        else:
            return False

    @property
    def anciennete(self):
        if self.date_entree:
            current_date = timezone.now().date()
            delta = current_date - self.date_entree
            years = delta.days // 365
            months = (delta.days % 365) // 30
            days = delta.days % 30
            return f"{years} an(s), {months} mois"
        return None

    def age(self):
        if self.birthdate:
            current_date = timezone.now().date()
            delta = current_date.year - self.birthdate.year
            anniversaire_passe = (
                    current_date.month > self.birthdate.month or
                    (current_date.month == self.birthdate.month and current_date.day >= self.birthdate.day))
            age = delta - (not anniversaire_passe)
            return age
        return None

    @property
    def statut(self):
        """
        Détermine le statut du fidèle en tant que visiteur si la date d'entrée est inférieure à 3 mois
        et que le champ membre est égal à 0.
        """
        if self.membre == 1:
            return "Membre actif"
        elif self.membre == 2:
            return "FISS"
        elif self.date_entree:
            # Calculer la différence en jours entre la date d'entrée et la date actuelle
            difference = (date.today() - self.date_entree).days
            # Vérifier si la différence est inférieure à 3 mois (90 jours)
            if difference < 90 and self.membre == 0:
                return "Visiteur"
        return "Sympathisant"


class FidelePosition(models.Model):
    SOURCES = (
        ("manual", "Manual"),
        ("browser", "Browser"),
        ("mobile_gps", "Mobile GPS"),
        ("other", "Other"),
    )

    fidele = models.ForeignKey("Fidele", on_delete=models.CASCADE, related_name="positions")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)  # -90..90
    longitude = models.DecimalField(max_digits=9, decimal_places=6)  # -180..180
    accuracy = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)  # en mètres
    captured_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=20, choices=SOURCES, default="manual")
    note = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["fidele", "captured_at"]),
        ]
        ordering = ["-captured_at"]

    def __str__(self):
        return f"{self.fidele_id} @ ({self.latitude}, {self.longitude}) {self.captured_at:%Y-%m-%d %H:%M}"


class UserProfileCompletion(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_complete = models.BooleanField(default=False)
    current_step = models.PositiveIntegerField(default=1)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profil de {self.user.username} - {'Complet' if self.is_complete else 'Incomplet'}"


class EntretienPastoral(models.Model):
    class TypeEntretien(models.TextChoices):
        SPIRITUEL = 'SPI', 'Entretien spirituel'
        DISCIPLINE = 'DIS', 'Discipline'
        ACCOMPAGNEMENT = 'ACC', 'Accompagnement'
        CRISE = 'CRI', 'Situation de crise'

    fidele = models.ForeignKey(Fidele, on_delete=models.CASCADE, related_name='entretiens')
    type_entretien = models.CharField(max_length=3, choices=TypeEntretien.choices)
    date = models.DateTimeField()
    pasteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='entretiens_conduits')
    resume = models.TextField()
    actions = models.TextField(blank=True)
    confidential = models.BooleanField(default=False)
    suivi_requis = models.BooleanField(default=False)
    date_suivi = models.DateField(null=True, blank=True)


class NotePastorale(models.Model):
    class Confidentialite(models.TextChoices):
        PUBLIC = 'PUB', 'Public'
        PRIVE = 'PRI', 'Privé'
        CONFIDENTIEL = 'CON', 'Confidentiel'

    fidele = models.ForeignKey('Fidele', on_delete=models.CASCADE, related_name='notes_pastorales')
    auteur = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notes_redigees')
    date = models.DateTimeField(auto_now_add=True)
    titre = models.CharField(max_length=200)
    contenu = models.TextField()
    confidentialite = models.CharField(max_length=3, choices=Confidentialite.choices, default=Confidentialite.PRIVE)
    tags = models.CharField(max_length=200, blank=True)


class Conseil(models.Model):
    class TypeConseil(models.TextChoices):
        MATRIMONIAL = 'MAT', 'Conseil matrimonial'
        FAMILIAL = 'FAM', 'Conseil familial'
        FINANCIER = 'FIN', 'Conseil financier'
        SPIRITUEL = 'SPI', 'Conseil spirituel'
        PROFESSIONNEL = 'PRO', 'Orientation professionnelle'

    conseillers = models.ManyToManyField(User, related_name='conseils_donnes')
    participants = models.ManyToManyField(Fidele, related_name='conseils_recus')
    date_conseil = models.DateTimeField()
    type_conseil = models.CharField(max_length=3, choices=TypeConseil.choices)
    sujet = models.CharField(max_length=200)
    notes = models.TextField()
    recommandations = models.TextField()
    confidential = models.BooleanField(default=True)
    suivi_requis = models.BooleanField(default=False)


class DemandePriere(models.Model):
    class StatutPriere(models.TextChoices):
        ACTIVE = 'ACT', 'Active'
        REPONDUE = 'REP', 'Répondue'
        EN_COURS = 'ENC', 'En cours'

    demandeur = models.ForeignKey(Fidele, on_delete=models.CASCADE, related_name='demandes_priere')
    date_demande = models.DateTimeField(auto_now_add=True)
    sujet = models.CharField(max_length=200)
    details = models.TextField()
    statut = models.CharField(max_length=3, choices=StatutPriere.choices, default=StatutPriere.ACTIVE)
    equipe_priere = models.ManyToManyField(User, related_name='prieres_assignees', blank=True)
    date_reponse = models.DateField(null=True, blank=True)
    temoignage = models.TextField(blank=True)
    publique = models.BooleanField(default=False)


class TransferHistory(models.Model):
    fidele = models.ForeignKey(Fidele, on_delete=models.CASCADE, related_name='transferts')
    ancienne_eglise = models.ForeignKey(Eglise, on_delete=models.SET_NULL, null=True, related_name='sorties')
    nouvelle_eglise = models.ForeignKey(Eglise, on_delete=models.CASCADE, related_name='entrees')
    date_transfert = models.DateTimeField(auto_now_add=True)
    effectue_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    motif = models.TextField()

    class Meta:
        ordering = ['-date_transfert']
        verbose_name_plural = "Historique des transferts"

    def __str__(self):
        return f"Transfert de {self.fidele} le {self.date_transfert}"


User = get_user_model()


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='actions')
    verb = models.CharField(max_length=255)
    target_url = models.URLField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    timestamp = models.DateTimeField(default=now)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.actor} {self.verb}"


class Competence(models.Model):
    nom = models.CharField(max_length=100)
    categorie = models.CharField(max_length=50)
    description = models.TextField(blank=True)


class Service(models.Model):
    nom = models.CharField(max_length=100)
    date = models.DateField()
    responsable = models.ForeignKey(Fidele, on_delete=models.SET_NULL, null=True)
    participants = models.ManyToManyField(Fidele, through='ParticipationService', related_name='services_participes')
    description = models.TextField(blank=True)


class ParticipationService(models.Model):
    fidele = models.ForeignKey(Fidele, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    role = models.CharField(max_length=100)
    presence = models.BooleanField(default=False)
    notes = models.TextField(blank=True)


class Anniversaire(models.Model):
    fidele = models.ForeignKey(Fidele, on_delete=models.CASCADE, related_name='anniversaires')
    date_anniversaire = models.DateField()
    type_anniversaire = models.CharField(max_length=50, choices=[
        ('NAISS', 'Anniversaire de naissance'),
        ('BAPT', 'Anniversaire de baptême'),
        ('MARI', 'Anniversaire de mariage'),
        ('CONV', 'Anniversaire de conversion')
    ])
    celebration_organisee = models.BooleanField(default=False)
    date_celebration = models.DateField(null=True, blank=True)
    participants = models.ManyToManyField(Fidele, related_name='anniversaires_participes', blank=True)
    cadeau = models.TextField(blank=True)
    photos = models.FileField(upload_to='anniversaires/', blank=True)


class Sacrement(models.Model):
    class TypeSacrement(models.TextChoices):
        BAPTEME = 'BAP', 'Baptême'
        CENE = 'CEN', 'Sainte Cène'
        MARIAGE = 'MAR', 'Mariage'
        ONCTION = 'ONC', 'Onction'
        RECONCILIATION = 'REC', 'Réconciliation'

    fidele = models.ForeignKey(Fidele, on_delete=models.CASCADE, related_name='sacrements')
    type_sacrement = models.CharField(max_length=3, choices=TypeSacrement.choices)
    date = models.DateField()
    officiant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sacrements_adminitres')
    lieu = models.CharField(max_length=200)
    temoins = models.ManyToManyField(Fidele, related_name='sacrements_temoignes', blank=True)
    documents = models.FileField(upload_to='sacrements/', blank=True)
    notes = models.TextField(blank=True)


class Deces(models.Model):
    defunt = models.OneToOneField(Fidele, on_delete=models.CASCADE, related_name='deces')
    date_deces = models.DateField()
    lieu_deces = models.CharField(max_length=200)
    cause = models.CharField(max_length=200, blank=True)
    date_ceremonie = models.DateField()
    lieu_ceremonie = models.CharField(max_length=200)
    officiant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='ceremonies_deces')
    hommage = models.TextField(blank=True)
    participants = models.ManyToManyField(Fidele, related_name='ceremonies_deces_participes', blank=True)


class PrayerCategory(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    icon = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PrayerRequest(models.Model):
    PRAYER = 'PR'
    EXHORTATION = 'EX'
    INTERCESSION = 'IN'
    TYPE_CHOICES = [
        (PRAYER, 'Prière'),
        (EXHORTATION, 'Exhortation'),
        (INTERCESSION, 'Intercession'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='prayers')
    category = models.ForeignKey(
        PrayerCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='prayers'
    )
    title = models.CharField(max_length=200, db_index=True)
    content = models.TextField()
    prayer_type = models.CharField(max_length=2, choices=TYPE_CHOICES, default=PRAYER, db_index=True)
    audio_note = models.FileField(upload_to='prayer_audios/', null=True, blank=True)
    is_anonymous = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class PrayerAttachment(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = 'image', 'Image'
        AUDIO = 'audio', 'Audio'

    prayer = models.ForeignKey(PrayerRequest, related_name='attachments', on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=MediaType.choices)
    file = models.FileField(upload_to='prayers/')
    created_at = models.DateTimeField(auto_now_add=True)


class PrayerComment(models.Model):
    prayer = models.ForeignKey(PrayerRequest, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='prayer_comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.user} on {self.prayer_id}"


class PrayerLike(models.Model):
    prayer = models.ForeignKey(PrayerRequest, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='prayer_likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('prayer', 'user')
        indexes = [models.Index(fields=['prayer', 'user'])]


class BibleVersion(models.Model):
    code = models.CharField(max_length=16, unique=True)  # ex: "LSG"
    name = models.CharField(max_length=128)              # ex: "Louis Segond 1910"
    language = models.CharField(max_length=16, default="fr")
    total_verses = models.PositiveIntegerField(default=0)
    # permet au client de savoir s'il doit resynchroniser
    etag = models.CharField(max_length=64, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self): return self.code


class BibleVerse(models.Model):
    version = models.ForeignKey(BibleVersion, on_delete=models.CASCADE, related_name="verses")
    book = models.CharField(max_length=64)             # "Genèse"
    chapter = models.PositiveIntegerField()
    verse = models.PositiveIntegerField()
    text = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("version", "book", "chapter", "verse")
        indexes = [
            models.Index(fields=["version", "book"]),
            models.Index(fields=["version", "book", "chapter"]),
        ]

    def __str__(self): return f"{self.version.code} {self.book} {self.chapter}:{self.verse}"