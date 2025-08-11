import datetime
import os
import random
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


class Evenement(models.Model):
    code = models.CharField(max_length=300, default=eventcode, unique=True, editable=False)
    eglise = models.ForeignKey('fidele.Eglise', on_delete=models.CASCADE, null=True, blank=True)
    titre = models.CharField(max_length=200)
    date_debut = models.DateTimeField(default=timezone.now)
    date_fin = models.DateTimeField(default=timezone.now)
    lieu = models.CharField(max_length=100)
    description = models.TextField()
    type = models.ForeignKey('TypeEvent', on_delete=models.CASCADE, null=True, blank=True)
    banner = models.ImageField(upload_to='event/banner/', null=True, blank=True)
    qr_code = models.ImageField(upload_to='qrcodes/', null=True, blank=True, editable=True)
    is_recurrent = models.BooleanField(default=False)
    recurrence_rule = models.TextField(null=True, blank=True)  # Pour stocker la règle de récurrence
    end_recurrence = models.DateTimeField(null=True, blank=True)  # Date de fin de récurrence

    # recurrence = RecurrenceField(null=True, blank=True)
    def generate_events(self):
        if not self.is_recurrent or not self.recurrence_rule:
            return [self]

        events = []
        start_date = self.date_debut
        end_recurrence = self.end_recurrence or (start_date + datetime.timedelta(days=365))  # Par défaut 1 an

        # Exemple de règle: "WEEKLY:SU" pour tous les dimanches
        freq, days = self.recurrence_rule.split(':')
        freq = freq.upper()
        days = days.upper()

        if freq == 'WEEKLY':
            freq = WEEKLY
            byweekday = []
            if 'SU' in days: byweekday.append(6)  # Dimanche
            if 'MO' in days: byweekday.append(0)  # Lundi
            if 'TU' in days: byweekday.append(1)  # Mardi
            if 'WE' in days: byweekday.append(2)  # Mercredi
            if 'TH' in days: byweekday.append(3)  # Jeudi
            if 'FR' in days: byweekday.append(4)  # Vendredi
            if 'SA' in days: byweekday.append(5)  # Samedi
        elif freq == 'MONTHLY':
            freq = MONTHLY
        elif freq == 'YEARLY':
            freq = YEARLY
        else:
            freq = DAILY

        rule = rrule(
            freq=freq,
            dtstart=start_date,
            until=end_recurrence,
            byweekday=byweekday if 'byweekday' in locals() else None
        )

        for i, occurrence in enumerate(rule):
            # Créer un nouvel événement pour chaque occurrence
            new_event = Evenement(
                titre=self.titre,
                date_debut=occurrence,
                date_fin=occurrence + (self.date_fin - self.date_debut),
                lieu=self.lieu,
                description=self.description,
                type=self.type,
                is_recurrent=False,
                recurrence_rule=None,
                end_recurrence=None
            )
            events.append(new_event)

        return events

    # def save(self, *args, **kwargs):
    #     # Générer le QR code seulement si l'événement n'est pas récurrent
    #     if not self.is_recurrent:
    #         self.generate_and_save_qr_code('data')
    #
    #     super().save(*args, **kwargs)
    #
    #     if self.banner:
    #         img = Image.open(self.banner.path)
    #         new_size = (1420, 560)
    #         img = img.resize(new_size, Image.LANCZOS)
    #         img.save(self.banner.path)
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
        if not self.qr_code:  # ne régénère pas si déjà présent
            self.generate_and_save_qr_code(self.code)
        super().save(*args, **kwargs)

        if self.banner:
            img = Image.open(self.banner.path)

            # Redimensionnez l'image en 1420x560
            new_size = (1420, 560)
            img = img.resize(new_size, Image.LANCZOS)

            # Sauvegardez l'image redimensionnée
            img.save(self.banner.path)

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