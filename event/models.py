import datetime
import os
import random
import uuid
from io import BytesIO

import qrcode
from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db import models
from django.utils import timezone
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY, YEARLY
from recurrence.fields import RecurrenceField


from fidele.models import User


def eventcode():
    code = ("EV" + str(random.randrange(0, 999999999, 1)))
    return code


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
    img.save(buffer, format="PNG")  # Save the image to the buffer in PNG format
    return buffer.getvalue()


# Create your models here.
class TypeEvent(models.Model):
    name = models.CharField(max_length=200)

    def __str__(self):
        return f'{self.name}  '

WEEKDAYS_MAP = {"MO":0, "TU":1, "WE":2, "TH":3, "FR":4, "SA":5, "SU":6}
WEEKDAYS_FR2EN = {"LU":"MO", "MA":"TU", "ME":"WE", "JE":"TH", "VE":"FR", "SA":"SA", "DI":"SU"}

class Evenement(models.Model):
    code = models.CharField(max_length=300, default=eventcode, unique=True, editable=False)

    # 🎯 clé de “série” pour grouper les occurrences et assurer l’idempotence
    series_id = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)

    eglise = models.ForeignKey('fidele.Eglise', on_delete=models.CASCADE, null=True, blank=True)
    titre = models.CharField(max_length=200)
    date_debut = models.DateTimeField(default=timezone.now)
    date_fin= models.DateTimeField(default=timezone.now)
    lieu = models.CharField(max_length=100)
    description = models.TextField()
    type = models.ForeignKey('TypeEvent', on_delete=models.CASCADE, null=True, blank=True)
    banner = models.ImageField(upload_to='event/banner/', null=True, blank=True)
    qr_code = models.ImageField(upload_to='qrcodes/', null=True, blank=True, editable=True)

    is_recurrent = models.BooleanField(default=False)
    recurrence_rule = models.TextField(null=True, blank=True)     # "WEEKLY:SU,WE" | "DAILY" | "MONTHLY" | "YEARLY"
    end_recurrence = models.DateTimeField(null=True, blank=True)  # fin de récurrence

    # Lien optionnel vers le parent (l’événement source) pour naviguer
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')


    class Meta:
        indexes = [
            models.Index(fields=["eglise", "date_debut"]),
            models.Index(fields=["date_fin"]),
            models.Index(fields=["series_id"]),
        ]
        # ⚠️ Unicité par série + fenêtres de temps
        constraints = [
            models.UniqueConstraint(
                fields=["series_id", "date_debut", "date_fin"],
                name="uniq_event_series_window"
            )
        ]

        # ---------- Validation ----------

    def clean(self):
        if self.is_recurrent:
            if not self.recurrence_rule:
                raise ValidationError("Pour un événement récurrent, 'recurrence_rule' est requis.")
            if not self.end_recurrence:
                # défaut robuste : +1 an
                self.end_recurrence = (self.date_debut + datetime.timedelta(days=365))
            if self.end_recurrence <= self.date_debut:
                raise ValidationError("'end_recurrence' doit être postérieure à 'date_debut'.")
        super().clean()
        # ---------- Parsing règle ----------

    def _parse_rule(self):
        rule = (self.recurrence_rule or "").strip().upper()
        if not rule:
            return DAILY, None

        if ":" in rule:
            freq_str, days_str = rule.split(":", 1)
            raw_days = [d.strip() for d in days_str.split(",") if d.strip()]
        else:
            freq_str, raw_days = rule, []

        days = []
        for d in raw_days:
            if d in WEEKDAYS_MAP:
                days.append(d)
            elif d in WEEKDAYS_FR2EN:
                days.append(WEEKDAYS_FR2EN[d])

        if freq_str == "WEEKLY":
            byweekday = [WEEKDAYS_MAP[d] for d in days if d in WEEKDAYS_MAP]
            if not byweekday:
                byweekday = [self.date_debut.weekday()]
            return WEEKLY, byweekday
        if freq_str == "MONTHLY":
            return MONTHLY, None
        if freq_str == "YEARLY":
            return YEARLY, None
        return DAILY, None
    # recurrence = RecurrenceField(null=True, blank=True)
    # ---------- Génération des occurrences (en mémoire) ----------
    def build_occurrences(self):
        """
        Construit les objets Evenement (non sauvegardés) de la série.
        - saute la première occurrence (celle-ci)
        - conserve la durée
        - copie les champs utiles
        """
        if not self.is_recurrent or not self.recurrence_rule or not self.end_recurrence:
            return []

        start = self.date_debut
        end_limit = self.end_recurrence
        if timezone.is_naive(start):
            start = timezone.make_aware(start, timezone.get_current_timezone())
        if timezone.is_naive(end_limit):
            end_limit = timezone.make_aware(end_limit, timezone.get_current_timezone())

        freq, byweekday = self._parse_rule()
        rule = rrule(freq=freq, dtstart=start, until=end_limit,
                     byweekday=byweekday if byweekday is not None else None)

        duration = self.date_fin - self.date_debut
        occurrences = []
        for occ in rule:
            if occ == start:
                continue
            ev = Evenement(
                series_id=self.series_id,  # ⚠️ même série
                parent=self,  # lien parent
                eglise=self.eglise,
                titre=self.titre,
                date_debut=occ,
                date_fin=occ + duration,
                lieu=self.lieu,
                description=self.description,
                type=self.type,
                is_recurrent=False,
                recurrence_rule=None,
                end_recurrence=None,
            )
            if self.banner:
                ev.banner = self.banner  # même fichier
            occurrences.append(ev)
        return occurrences

    def generate_and_save_qr_code(self, data):
        image_data = generate_qr_code(self.code)
        image = Image.open(BytesIO(image_data))

        # Create a unique filename for the QR code image
        filename = f'qr_code_{self.code}.png'

        # Create a Django InMemoryUploadedFile for the ImageField
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        image_file = InMemoryUploadedFile(buffered, None, filename, 'image/png', len(buffered.getvalue()), None)

        # Save the InMemoryUploadedFile to the ImageField
        self.qr_code.save(filename, image_file, save=False)

        return self.qr_code

    def is_same_date(self):
        return self.date_debut.date() == self.date_fin.date()

    def save(self, *args, **kwargs):
        if not self.qr_code:
            self.generate_and_save_qr_code(self.code)
        super().save(*args, **kwargs)

        if self.banner:
            try:
                img = Image.open(self.banner.path)
                new_size = (1420, 560)
                img = img.resize(new_size, Image.LANCZOS)
                img.save(self.banner.path)
            except Exception:
                # évite de crasher si le fichier n'existe pas encore en FS (ex: storage distant)
                pass
    def __str__(self):
        return f'{self.titre} {self.date_debut} {self.code}'

    @property
    def invites_potentiels(self):
        from fidele.models import Fidele
        """
        Retourne tous les fidèles de l'église comme invités potentiels
        """
        if self.eglise:
            return Fidele.objects.filter(eglise=self.eglise, is_deleted=0)
        return Fidele.objects.none()

    @property
    def nombre_participants(self):
        return ParticipationEvenement.objects.filter(evenement=self).count()

    @property
    def liste_participants(self):
        return ParticipationEvenement.objects.filter(evenement=self).all()

    @property
    def taux_participation(self):
        from fidele.models import Fidele
        total_participants = Fidele.objects.count()  # Modifier selon votre modèle Fidele
        if total_participants > 0:
            return round((self.nombre_participants / total_participants) * 100, 2)
        return 0
    @property
    def nombre_invite(self):
        from fidele.models import Fidele
        invites = Fidele.objects.count()
        return invites


class ParticipationEvenement(models.Model):
    # from fidele.models import Fidele
    fidele = models.ForeignKey('fidele.Fidele', on_delete=models.CASCADE)
    evenement = models.ForeignKey(Evenement, on_delete=models.CASCADE)
    commentaire = models.TextField(null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    qr_code_scanned = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.fidele} {self.evenement} {self.date}'

    class Meta:
        # Ajoutez une contrainte unique pour garantir qu'un participant ne peut pas être enregistré deux fois
        unique_together = ('fidele', 'evenement',)

    def clean(self):
        # Validez que la même personne ne peut pas être enregistrée deux fois
        existing_participations = ParticipationEvenement.objects.filter(
            fidele=self.fidele,
            evenement=self.evenement,
            # date=self.date
        ).exclude(pk=self.pk)  # Exclure l'instance actuelle lors de la vérification d'unicité

        if existing_participations.exists():
            raise ValidationError('Cette personne est déjà enregistrée pour cet événement.')


class VisiteDomicile(models.Model):
    class TypeVisite(models.TextChoices):
        PASTORALE = 'PAS', 'Pastorale'
        EVANGELISATION = 'EVA', 'Évangélisation'
        SUIVI = 'SUI', 'Suivi'
        CRISE = 'CRI', 'Crise familiale'

    visiteurs = models.ManyToManyField(User, related_name='visites_effectuees')
    foyers = models.ManyToManyField('fidele.Fidele', related_name='visites_recues')
    date_visite = models.DateTimeField()
    duree = models.DurationField(help_text="Durée en heures:minutes")
    type_visite = models.CharField(max_length=3, choices=TypeVisite.choices)
    compte_rendu = models.TextField()
    actions_suivi = models.TextField(blank=True)
    date_prochaine_visite = models.DateField(null=True, blank=True)
    documents = models.FileField(upload_to='visites/', blank=True)