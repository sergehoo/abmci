from django.db import models

from fidele.models import Fidele, User


# Create your models here.
class Fiancailles(models.Model):
    homme = models.ForeignKey(Fidele, on_delete=models.CASCADE, related_name='fiancailles_homme')
    femme = models.ForeignKey(Fidele, on_delete=models.CASCADE, related_name='fiancailles_femme')
    date_demande = models.DateField()
    date_ceremonie = models.DateField()
    lieu_ceremonie = models.CharField(max_length=200)
    conseiller = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='fiancailles_conseillees')
    sessions_conseil = models.PositiveIntegerField(default=3)
    sessions_terminees = models.PositiveIntegerField(default=0)
    statut = models.CharField(max_length=20, default='En cours')
    documents = models.FileField(upload_to='fiancailles/', blank=True)


class Mariage(models.Model):
    couple = models.ManyToManyField(Fidele, related_name='mariages')
    date_mariage = models.DateField()
    lieu_mariage = models.CharField(max_length=200)
    officiant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='mariages_officies')
    temoins = models.ManyToManyField(Fidele, related_name='mariages_temoignes', blank=True)
    numero_acte = models.CharField(max_length=50, blank=True)
    contrat_matrimonial = models.FileField(upload_to='mariages/contrats/', blank=True)
    photos = models.FileField(upload_to='mariages/photos/', blank=True)
    notes = models.TextField(blank=True)



