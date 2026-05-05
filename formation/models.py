"""
Modèles du module Formations Alliance Connect.

Hiérarchie :
    Formation (parcours catalogue) ──┐
                                     ├── FormationSession (promotion datée)
                                     │       ├── FormationModule (séance datée)
                                     │       │       └── FormationPresence (inscription × module)
                                     │       └── FormationInscription (fidèle × session)
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


# ============================================================================
# Catalogue
# ============================================================================

class Formation(models.Model):
    """Parcours de formation au catalogue (Pastorale, Baptême, Mariage, …)."""

    class Theme(models.TextChoices):
        PASTORALE = 'pastorale', 'Formation pastorale'
        BAPTEME   = 'bapteme',   'Préparation au baptême'
        MARIAGE   = 'mariage',   'Préparation au mariage'
        DISCIPULAT = 'disciple', 'Discipulat'
        AUTRE     = 'autre',     'Autre'

    GRADIENT_PRESETS = {
        'pastorale': ('brand-600', 'brand-700', 'violet-700', 'brand'),
        'bapteme':   ('cyan-500',  'sky-600',   'blue-700',   'cyan'),
        'mariage':   ('rose-500',  'pink-500',  'amber-500',  'rose'),
        'disciple':  ('emerald-500','emerald-600','teal-700','emerald'),
        'autre':     ('slate-500', 'slate-600', 'slate-700',  'slate'),
    }

    slug         = models.SlugField(max_length=80, unique=True)
    nom          = models.CharField(max_length=140)
    theme        = models.CharField(max_length=20, choices=Theme.choices, default=Theme.AUTRE)
    description  = models.TextField(blank=True)
    duree_mois   = models.PositiveSmallIntegerField(default=3)
    format      = models.CharField(max_length=120, blank=True,
                                    help_text="ex: Présentiel, En couple, Groupe de 8-12…")
    formateur_principal = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='formations_principales',
    )
    actif        = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['theme', 'nom']
        verbose_name = "Formation"
        verbose_name_plural = "Formations"

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        # Auto-génère un slug unique à partir du nom si vide
        if not self.slug:
            base = slugify(self.nom) or 'formation'
            slug = base
            n = 2
            while Formation.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('formation_detail', args=[self.slug or 'formation'])

    # Helpers UI
    @property
    def gradient(self) -> dict:
        f, v, t, accent = self.GRADIENT_PRESETS.get(self.theme, self.GRADIENT_PRESETS['autre'])
        return {'from': f, 'via': v, 'to': t, 'accent': accent}

    def sessions_actives(self):
        return self.sessions.filter(statut__in=[
            FormationSession.Statut.PLANIFIEE,
            FormationSession.Statut.EN_COURS,
        ])


# ============================================================================
# Sessions / Modules
# ============================================================================

class FormationSession(models.Model):
    """Promotion / instance datée d'un parcours."""

    class Statut(models.TextChoices):
        PLANIFIEE = 'planifiee', 'Planifiée'
        EN_COURS  = 'en_cours',  'En cours'
        TERMINEE  = 'terminee',  'Terminée'
        ANNULEE   = 'annulee',   'Annulée'

    formation     = models.ForeignKey(Formation, on_delete=models.CASCADE, related_name='sessions')
    nom           = models.CharField(max_length=140, help_text="ex: « Promo Septembre 2026 »")
    date_debut    = models.DateField()
    date_fin      = models.DateField(null=True, blank=True)
    lieu          = models.CharField(max_length=200, blank=True)
    capacite_max  = models.PositiveSmallIntegerField(default=20)
    statut        = models.CharField(max_length=12, choices=Statut.choices, default=Statut.PLANIFIEE)
    formateur     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sessions_animees',
    )
    notes         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_debut']
        verbose_name = "Session de formation"
        verbose_name_plural = "Sessions de formation"
        indexes = [models.Index(fields=['formation', '-date_debut'])]

    def __str__(self):
        return f"{self.formation.nom} — {self.nom}"

    def get_absolute_url(self):
        return reverse('formation_session_detail', args=[self.pk])

    @property
    def places_restantes(self) -> int:
        return max(0, self.capacite_max - self.inscriptions.exclude(
            statut=FormationInscription.Statut.ABANDONNE,
        ).count())

    @property
    def taux_remplissage(self) -> int:
        if self.capacite_max == 0:
            return 0
        actives = self.inscriptions.exclude(
            statut=FormationInscription.Statut.ABANDONNE,
        ).count()
        return min(100, round(actives / self.capacite_max * 100))

    @property
    def progression(self) -> int:
        """Avancement temporel de la session (en %)."""
        if not self.date_fin or self.date_fin <= self.date_debut:
            return 0 if self.statut == self.Statut.PLANIFIEE else 100
        today = timezone.localdate()
        if today <= self.date_debut:
            return 0
        if today >= self.date_fin:
            return 100
        total = (self.date_fin - self.date_debut).days
        done  = (today - self.date_debut).days
        return round(done / total * 100)


class FormationModule(models.Model):
    """Séance / module d'une session."""

    session     = models.ForeignKey(FormationSession, on_delete=models.CASCADE, related_name='modules')
    ordre       = models.PositiveSmallIntegerField(default=1)
    titre       = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    date_seance = models.DateTimeField(null=True, blank=True)
    duree_minutes = models.PositiveSmallIntegerField(default=90)

    class Meta:
        ordering = ['session', 'ordre']
        verbose_name = "Module de formation"
        verbose_name_plural = "Modules de formation"
        indexes = [models.Index(fields=['session', 'ordre'])]

    def __str__(self):
        return f"{self.ordre:02d}. {self.titre}"


# ============================================================================
# Inscriptions et présences
# ============================================================================

class FormationInscription(models.Model):
    """Inscription d'un fidèle à une session de formation."""

    class Statut(models.TextChoices):
        ACTIF      = 'actif',      'Actif'
        ABANDONNE  = 'abandonne',  'Abandonné'
        DIPLOME    = 'diplome',    'Diplômé'
        ECHEC      = 'echec',      'Non validé'

    session       = models.ForeignKey(FormationSession, on_delete=models.CASCADE, related_name='inscriptions')
    fidele        = models.ForeignKey('fidele.Fidele', on_delete=models.CASCADE, related_name='formations_inscrites')
    date_inscription = models.DateTimeField(auto_now_add=True)
    statut        = models.CharField(max_length=12, choices=Statut.choices, default=Statut.ACTIF)
    note_finale   = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Note globale (0-20)")
    commentaire   = models.TextField(blank=True)

    class Meta:
        ordering = ['-date_inscription']
        unique_together = [('session', 'fidele')]
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"

    def __str__(self):
        return f"{self.fidele} → {self.session}"

    @property
    def taux_presence(self) -> int:
        modules = self.session.modules.all()
        total = modules.count()
        if total == 0:
            return 0
        present = self.presences.filter(present=True).count()
        return round(present / total * 100)


class FormationPresence(models.Model):
    """Présence d'un inscrit à un module."""

    inscription = models.ForeignKey(FormationInscription, on_delete=models.CASCADE, related_name='presences')
    module      = models.ForeignKey(FormationModule,      on_delete=models.CASCADE, related_name='presences')
    present     = models.BooleanField(default=False)
    excuse      = models.CharField(max_length=140, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('inscription', 'module')]
        ordering = ['module__ordre']
        verbose_name = "Présence"
        verbose_name_plural = "Présences"
