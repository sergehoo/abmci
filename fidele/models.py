from __future__ import annotations

import random
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import now
from simple_history.models import HistoricalRecords
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from django.contrib.gis.db import models as gis_models
from tinymce.models import HTMLField  # 👈
from abmci.notifications.fcm import send_verse_to_eglise_topic

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
    platform = models.CharField(max_length=20, choices=[('android', 'Android'), ('ios', 'iOS')])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(auto_now=True)


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
    location = gis_models.PointField(srid=4326, null=True, blank=True, spatial_index=True)
    verse_du_jour = models.TextField(null=True, blank=True)
    verse_reference = models.CharField(max_length=100, null=True, blank=True)
    verse_date = models.DateField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            # Django 5.1+ ; sinon: models.Index + db_index via migration
        ]

    def _verset_changed(self, old_text: str | None, old_ref: str | None) -> bool:
        """Détecte un changement ‘réel’ (on compacte les espaces)."""

        def _norm(s: str | None) -> str:
            return " ".join((s or "").split())

        return _norm(old_text) != _norm(self.verse_du_jour) or _norm(old_ref) != _norm(self.verse_reference)

    def save(self, *args, **kwargs):
        """
        - Met à jour verse_date si verset ou référence changent.
        - Envoie une notification FCM APRÈS commit si changement (sauf skip explicite).
        Note: bulk_update() ne passe pas ici.
        """
        skip_notify: bool = kwargs.pop("skip_notify", False)

        # Récupérer l'ancien état pour comparer
        old_text = old_ref = None
        if self.pk:
            try:
                old = Eglise.objects.only("verse_du_jour", "verse_reference").get(pk=self.pk)
                old_text, old_ref = old.verse_du_jour, old.verse_reference
            except Eglise.DoesNotExist:
                pass

        # Mettre à jour verse_date si nécessaire (y compris update_fields)
        update_fields = kwargs.get("update_fields")
        today = timezone.localdate()
        if update_fields:
            fields = set(update_fields)
            if {"verse_du_jour", "verse_reference"} & fields:
                self.verse_date = today
                kwargs["update_fields"] = list(fields | {"verse_date"})
        else:
            if self.pk and self._verset_changed(old_text, old_ref):
                self.verse_date = today

        # Enregistrement DB
        super().save(*args, **kwargs)

        # Notifier si le verset a changé et que l'on souhaite notifier

    def __str__(self):
        return self.name or "Église sans nom"


class ProblemCategory(models.Model):
    """Catégories configurables depuis l’admin."""
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(unique=True, editable=False)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Catégorie de problème"
        verbose_name_plural = "Catégories de problèmes"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug or self.name_changed():
            base_slug = slugify(self.name)
            slug = base_slug
            i = 1
            # garantir l’unicité du slug
            while ProblemCategory.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def name_changed(self) -> bool:
        """Vérifie si le champ name a changé (utile en édition)."""
        if not self.pk:
            return True
        old = ProblemCategory.objects.filter(pk=self.pk).only("name").first()
        return old and old.name != self.name

    def __str__(self):
        return self.name


class ProblemReport(models.Model):
    """
    Signalement d’un fidèle, imputé à un responsable pour traitement.
    Exemples: décès d'un parent, absence pour maladie/voyage, assistance sociale, etc.
    """

    class Severity(models.TextChoices):
        LOW = "LOW", "Faible"
        MEDIUM = "MED", "Moyenne"
        HIGH = "HIGH", "Élevée"
        CRITICAL = "CRIT", "Critique"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Ouvert"
        IN_PROGRESS = "WIP", "En cours"
        ON_HOLD = "HOLD", "En attente"
        RESOLVED = "DONE", "Résolu"
        CANCELED = "CANC", "Annulé"

    eglise = models.ForeignKey(Eglise, on_delete=models.CASCADE, related_name="problem_reports")
    assignee = models.ForeignKey('fidele.Fidele', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="assigned_problems")
    watchers = models.ManyToManyField('fidele.Fidele', blank=True, related_name="watched_problems")
    reporter = models.ForeignKey('fidele.Fidele', on_delete=models.CASCADE, related_name="problem_reports")
    category = models.ForeignKey(ProblemCategory, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=180)
    description = models.TextField()
    # Responsable (membre du staff, diacre, pasteur, cellule sociale…)
    severity = models.CharField(max_length=5, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=5, choices=Status.choices, default=Status.OPEN)
    due_date = models.DateField(null=True, blank=True)
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True, null=True)

    # Soft flags
    is_deleted = models.BooleanField(default=False)

    history = HistoricalRecords()

    class Meta:
        indexes = [
            models.Index(fields=["eglise", "status"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["created_at"]),
        ]
        permissions = (
            ("can_assign_problem", "Peut assigner un problème à un responsable"),
            ("can_view_all_problems", "Peut voir tous les problèmes de l'église"),
        )
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title}"

    def mark_resolved(self, notes: str | None = None, commit=True):
        self.status = self.Status.RESOLVED
        self.resolution_notes = notes or self.resolution_notes
        self.resolved_at = timezone.now()
        if commit:
            self.save(update_fields=["status", "resolution_notes", "resolved_at", "updated_at"])

    @property
    def is_overdue(self) -> bool:
        return bool(self.due_date and self.status not in {self.Status.RESOLVED, self.Status.CANCELED}
                    and timezone.localdate() > self.due_date)


class ProblemAction(models.Model):
    class Type(models.TextChoices):
        COMMENT = "COMMENT", "Commentaire"
        ASSIGN = "ASSIGN", "Assignation"
        STATUS = "STATUS", "Changement de statut"

    problem = models.ForeignKey('ProblemReport', on_delete=models.CASCADE, related_name='actions')
    author = models.ForeignKey('fidele.Fidele', on_delete=models.SET_NULL, null=True, blank=True)
    type = models.CharField(max_length=16, choices=Type.choices)
    message = models.TextField(blank=True)  # commentaire / note
    meta = models.JSONField(default=dict, blank=True)  # ex: {"old": "OPEN", "new": "WIP", "assignee_id": 123}
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


def default_problem_categories():
    """À appeler via loaddata ou migration (LOW code setup)."""
    base = [
        ("Décès / Assistance funérailles", "deces"),
        ("Maladie / Visite / Soutien", "maladie"),
        ("Voyage / Absence prolongée", "voyage"),
        ("Aide sociale / Urgence", "social"),
        ("Conseil pastoral", "conseil"),
    ]
    for name, slug in base:
        ProblemCategory.objects.get_or_create(slug=slug, defaults={"name": name})


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


def create_problem_report(*, reporter, eglise, title, description, category_slug=None, assignee=None, severity="MED",
                          due_date=None, watchers=None) -> ProblemReport:
    """
    Crée un signalement et déclenche les notifications post-commit.
    `reporter`: instance Fidele
    `eglise`: instance Eglise
    """
    category = None
    if category_slug:
        category = ProblemCategory.objects.filter(slug=category_slug, is_active=True).first()

    with transaction.atomic():
        pr = ProblemReport.objects.create(
            reporter=reporter,
            eglise=eglise,
            title=title,
            description=description,
            category=category,
            assignee=assignee,
            severity=severity,
            due_date=due_date,
        )
        if watchers:
            pr.watchers.add(*watchers)
    return pr


class Role(models.Model):
    """
    Rôle générique dans l’église (ex: PASTEUR, DIACRE, SECOURISTE, etc.)
    """
    code = models.CharField(max_length=50, unique=True)  # ex: "PASTEUR"
    name = models.CharField(max_length=100)  # ex: "Pasteur"
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Rôle"
        verbose_name_plural = "Rôles"

    def __str__(self):
        return f"{self.name} ({self.code})"


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
    roles = models.ManyToManyField('Role', blank=True, related_name='fideles')  # 👈 AJOUT
    created_at = models.DateTimeField(auto_now_add=now, )
    history = HistoricalRecords()

    def signaler_probleme(self, *, title: str, description: str,
                          category_slug: str | None = None, assignee=None,
                          severity: str = "MED", due_date=None, watchers=None):
        """
        Fonction demandée : le fidèle signale un problème.
        Retourne l'instance ProblemReport créée.
        """
        eglise = self.eglise  # sécurité multi-églises
        return create_problem_report(
            reporter=self, eglise=eglise, title=title, description=description,
            category_slug=category_slug, assignee=assignee, severity=severity,
            due_date=due_date, watchers=watchers
        )

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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fidelenotifications",  # <- unique
        related_query_name="fidelenotification",
    )
    type = models.CharField(max_length=40, default="GENERIC", db_index=True)
    title = models.CharField(max_length=200)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # db_table = "fidelenotification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["type"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} • {self.type} • {self.title[:32]}"

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
    name = models.CharField(max_length=128)  # ex: "Louis Segond 1910"
    language = models.CharField(max_length=16, default="fr")
    total_verses = models.PositiveIntegerField(default=0)
    # permet au client de savoir s'il doit resynchroniser
    etag = models.CharField(max_length=64, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self): return self.code


class BibleVerse(models.Model):
    version = models.ForeignKey(BibleVersion, on_delete=models.CASCADE, related_name="verses")
    book = models.CharField(max_length=64)  # "Genèse"
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


class BibleTag(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tags_sent')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tags_received')
    version = models.CharField(max_length=16)
    book = models.CharField(max_length=64)
    chapter = models.PositiveIntegerField()
    verse = models.PositiveIntegerField()
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['recipient', 'created_at'])]
        ordering = ['-created_at']

    def __str__(
            self): return f'{self.sender_id}→{self.recipient_id} {self.book} {self.chapter}:{self.verse} ({self.version})'


class VerseOfDay(models.Model):
    """
    Cache du verset du jour, par église, version et langue.
    Un enregistrement par (date, église).
    """
    date = models.DateField(default=timezone.localdate)
    eglise = models.ForeignKey('fidele.Eglise', on_delete=models.CASCADE, related_name='vods')
    version = models.CharField(max_length=16, default='LSG')
    language = models.CharField(max_length=16, default='fr')
    context_key = models.CharField(max_length=64, default='DEFAULT', db_index=True)
    text = models.TextField()
    reference = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True, db_index=True)


    class Meta:
        unique_together = (('date', 'eglise'),)
        indexes = [
            models.Index(fields=['eglise', 'date']),
            models.Index(fields=['version', 'language']),
            models.Index(fields=['date', 'notified_at']),
        ]

    def __str__(self):
        return f"{self.date} - {self.eglise_id} - {self.reference}"


def banner_upload_to(instance, filename):
    # ex: banners/2025/08/<filename>
    # Utilise created_at si déjà présent (update), sinon "maintenant" (création)
    dt = instance.created_at or timezone.now()
    return f"banners/{dt:%Y/%m}/{filename}"


class VerseUsage(models.Model):
    """
    Historique des versets utilisés par église, pour éviter les répétitions
    trop rapprochées (fenêtre glissante).
    """
    eglise = models.ForeignKey('fidele.Eglise', on_delete=models.CASCADE, related_name='verse_usages')
    used_on = models.DateField(default=timezone.localdate, db_index=True)
    version = models.CharField(max_length=16, default='LSG')
    book = models.CharField(max_length=64)
    chapter = models.PositiveIntegerField()
    verse = models.PositiveIntegerField()

    class Meta:
        indexes = [
            models.Index(fields=['eglise', 'used_on']),
            models.Index(fields=['eglise', 'book', 'chapter', 'verse']),
        ]

    def __str__(self):
        return f"{self.eglise_id} - {self.book} {self.chapter}:{self.verse} ({self.used_on})"


class Banner(models.Model):
    title = models.CharField(max_length=200, blank=True, default="")
    subtitle = models.CharField(max_length=300, blank=True, default="")
    details = HTMLField(blank=True)
    image = models.ImageField(upload_to=banner_upload_to)
    link_url = models.URLField(blank=True, default="")  # URL de redirection éventuelle
    active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)  # tri
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # pour ETag

    class Meta:
        ordering = ["order", "-updated_at"]

    def __str__(self):
        return self.title or f"Banner #{self.pk}"


class DonationCategory(models.Model):
    code = models.SlugField(unique=True)  # 'offering', 'tithe', 'special'
    name = models.CharField(max_length=120)
    min_amount = models.PositiveIntegerField(default=100)  # XOF/NGN entiers
    max_amount = models.PositiveIntegerField(default=10000000)

    def save(self, *args, **kwargs):
        # Générer automatiquement le slug si vide ou si name a changé
        if not self.code:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            # Vérifie unicité
            while DonationCategory.objects.filter(code=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.code = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Donation(models.Model):
    RECURRENCE_CHOICES = [
        ('none', 'None'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semiannual', 'Semiannual'),
    ]
    PAYMENT_METHODS = [('paystack', 'Paystack')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    anonymous = models.BooleanField(default=False)

    category = models.ForeignKey(DonationCategory, on_delete=models.PROTECT)
    amount = models.PositiveIntegerField()  # en XOF/NGN (unités entières, pas de centimes)
    currency = models.CharField(max_length=3, default="XOF")

    recurrence = models.CharField(max_length=16, choices=RECURRENCE_CHOICES, default='none')

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='paystack')
    reference = models.CharField(max_length=100, unique=True, db_index=True)

    status = models.CharField(max_length=20, default='pending')  # pending|success|failed|abandoned
    authorization_url = models.URLField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    meta = models.JSONField(default=dict, blank=True)  # optionnel

    def mark_success(self):
        if self.status != 'success':
            self.status = 'success'
            self.paid_at = timezone.now()
            self.save(update_fields=['status', 'paid_at'])

    def mark_failed(self, status='failed'):
        if self.status not in ('success', 'failed', 'abandoned'):
            self.status = status
            self.save(update_fields=['status'])

    def __str__(self):
        return f"{self.category.name} - {self.amount} {self.currency} ({self.status})"


class AccountDeletionRequest(models.Model):
    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("processing", "Processing"),
        ("done", "Done"),
        ("canceled", "Canceled"),
        ("failed", "Failed"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deletion_requests")
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="requested")
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-requested_at",)

    def __str__(self):
        return f"DeletionRequest(user={self.user_id}, status={self.status})"
