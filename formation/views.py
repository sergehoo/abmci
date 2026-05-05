"""Vues du module Formations."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView,
)

from formation.forms import (
    FormationForm, FormationModuleForm, FormationSessionForm,
    FormationInscriptionForm,
)
from formation.models import (
    Formation, FormationInscription, FormationModule, FormationPresence,
    FormationSession,
)


# ============================================================================
# Catalogue (parcours)
# ============================================================================

class FormationCatalogView(LoginRequiredMixin, ListView):
    """Catalogue des parcours actifs avec stats globales."""
    template_name = 'formations/index.html'
    model = Formation
    context_object_name = 'formations'

    def get_queryset(self):
        return (Formation.objects.filter(actif=True)
                .annotate(nb_sessions=Count('sessions', distinct=True))
                .order_by('theme', 'nom'))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Stats globales
        sessions_qs = FormationSession.objects.all()
        inscr_qs    = FormationInscription.objects.all()
        ctx['stats'] = {
            'total':      Formation.objects.filter(actif=True).count(),
            'actifs':     inscr_qs.filter(statut=FormationInscription.Statut.ACTIF).count(),
            'diplomes':   inscr_qs.filter(statut=FormationInscription.Statut.DIPLOME).count(),
            'sessions':   sessions_qs.filter(statut__in=[
                              FormationSession.Statut.PLANIFIEE,
                              FormationSession.Statut.EN_COURS,
                          ]).count(),
            'formateurs': Formation.objects.filter(actif=True)
                              .values('formateur_principal').distinct().count(),
        }
        return ctx


class FormationDetailView(LoginRequiredMixin, DetailView):
    """Détail d'un parcours + ses sessions."""
    template_name = 'formations/formation_detail.html'
    model = Formation
    context_object_name = 'formation'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['sessions'] = (self.object.sessions
                           .select_related('formateur')
                           .annotate(nb_inscrits=Count('inscriptions'))
                           .order_by('-date_debut'))
        ctx['accent']    = self.object.gradient
        return ctx


class FormationCreateView(LoginRequiredMixin, CreateView):
    template_name = 'formations/formation_form.html'
    form_class    = FormationForm
    success_url   = reverse_lazy('formations_index')


class FormationUpdateView(LoginRequiredMixin, UpdateView):
    template_name = 'formations/formation_form.html'
    form_class    = FormationForm
    model         = Formation


# ============================================================================
# Sessions
# ============================================================================

class FormationSessionDetailView(LoginRequiredMixin, DetailView):
    """Détail d'une session : modules, inscrits, présences."""
    template_name = 'formations/session_detail.html'
    model = FormationSession
    context_object_name = 'session'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        s = self.object
        ctx['accent']  = s.formation.gradient
        ctx['modules'] = list(s.modules.order_by('ordre'))
        ctx['inscriptions'] = (s.inscriptions
                               .select_related('fidele', 'fidele__user')
                               .order_by('fidele__user__last_name'))
        # Matrice présences pour le tableau de pointage
        presences = FormationPresence.objects.filter(
            inscription__session=s
        ).values('inscription_id', 'module_id', 'present')
        matrix = {}
        for p in presences:
            matrix.setdefault(p['inscription_id'], {})[p['module_id']] = p['present']
        ctx['presence_matrix'] = matrix
        ctx['inscription_form'] = FormationInscriptionForm(session=s)
        ctx['module_form']      = FormationModuleForm()
        return ctx


class FormationSessionCreateView(LoginRequiredMixin, CreateView):
    template_name = 'formations/session_form.html'
    form_class    = FormationSessionForm

    def get_initial(self):
        initial = super().get_initial()
        # Pré-remplir formation si fournie en query param
        formation_slug = self.request.GET.get('formation')
        if formation_slug:
            try:
                initial['formation'] = Formation.objects.get(slug=formation_slug)
            except Formation.DoesNotExist:
                pass
        return initial

    def form_valid(self, form):
        messages.success(self.request, "Nouvelle session de formation programmée.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('formation_session_detail', args=[self.object.pk])


class FormationSessionUpdateView(LoginRequiredMixin, UpdateView):
    template_name = 'formations/session_form.html'
    form_class    = FormationSessionForm
    model         = FormationSession

    def get_success_url(self):
        return reverse_lazy('formation_session_detail', args=[self.object.pk])


class FormationSessionDeleteView(LoginRequiredMixin, DeleteView):
    template_name = 'formations/session_confirm_delete.html'
    model         = FormationSession
    success_url   = reverse_lazy('formations_index')


# ============================================================================
# Modules (séances)
# ============================================================================

class FormationModuleCreateView(LoginRequiredMixin, CreateView):
    template_name = 'formations/module_form.html'
    form_class    = FormationModuleForm

    def dispatch(self, request, *args, **kwargs):
        self.session = get_object_or_404(FormationSession, pk=kwargs['session_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        # Auto-incrémente l'ordre
        last = self.session.modules.order_by('-ordre').first()
        initial['ordre'] = (last.ordre + 1) if last else 1
        return initial

    def form_valid(self, form):
        form.instance.session = self.session
        messages.success(self.request, f"Module « {form.instance.titre} » ajouté.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('formation_session_detail', args=[self.session.pk])


# ============================================================================
# Inscriptions
# ============================================================================

class FormationInscrireView(LoginRequiredMixin, CreateView):
    template_name = 'formations/inscription_form.html'
    form_class    = FormationInscriptionForm

    def dispatch(self, request, *args, **kwargs):
        self.session = get_object_or_404(FormationSession, pk=kwargs['session_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        k = super().get_form_kwargs()
        k['session'] = self.session
        return k

    def form_valid(self, form):
        if self.session.places_restantes <= 0:
            messages.error(self.request, "Aucune place restante dans cette session.")
            return self.form_invalid(form)
        form.instance.session = self.session
        # Crée automatiquement les enregistrements de présence pour tous les modules
        with transaction.atomic():
            response = super().form_valid(form)
            for module in self.session.modules.all():
                FormationPresence.objects.get_or_create(
                    inscription=self.object, module=module,
                    defaults={'present': False},
                )
        messages.success(self.request, f"{form.instance.fidele} inscrit(e) avec succès.")
        return response

    def get_success_url(self):
        return reverse_lazy('formation_session_detail', args=[self.session.pk])


class MesInscriptionsView(LoginRequiredMixin, ListView):
    """Inscriptions de l'utilisateur courant (en tant que fidèle)."""
    template_name = 'formations/mes_inscriptions.html'
    context_object_name = 'inscriptions'

    def get_queryset(self):
        fidele = getattr(self.request.user, 'fidele', None)
        if not fidele:
            return FormationInscription.objects.none()
        return (FormationInscription.objects
                .filter(fidele=fidele)
                .select_related('session', 'session__formation')
                .order_by('-date_inscription'))


# ============================================================================
# Endpoints AJAX — pointage des présences
# ============================================================================

@method_decorator(require_POST, name='dispatch')
class TogglePresenceView(LoginRequiredMixin, TemplateView):
    """
    POST /formations/sessions/<session_pk>/presence/toggle/
        body: inscription=<id>&module=<id>&present=true|false
    Renvoie JSON {ok, present, taux_presence_inscription}
    """
    def post(self, request, session_pk, *args, **kwargs):
        session = get_object_or_404(FormationSession, pk=session_pk)
        try:
            inscription = session.inscriptions.get(pk=request.POST['inscription'])
            module      = session.modules.get(pk=request.POST['module'])
        except (KeyError, FormationInscription.DoesNotExist, FormationModule.DoesNotExist):
            return HttpResponseBadRequest("Paramètres invalides.")

        present = request.POST.get('present', '').lower() in ('1', 'true', 'on', 'yes')
        excuse  = request.POST.get('excuse', '').strip()
        obj, _ = FormationPresence.objects.update_or_create(
            inscription=inscription, module=module,
            defaults={'present': present, 'excuse': excuse},
        )
        return JsonResponse({
            'ok': True,
            'present': obj.present,
            'taux': inscription.taux_presence,
        })
