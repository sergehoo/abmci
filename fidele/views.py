from __future__ import annotations

from collections import defaultdict
from datetime import timedelta, date
from io import BytesIO

from allauth.account.forms import LoginForm
from allauth.utils import generate_unique_username
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.forms.models import construct_instance
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

from abmci.access import StaffRequiredMixin, staff_required
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q, Case, When, IntegerField, Sum
from django.http import HttpRequest, HttpResponse, FileResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView, ListView, DetailView, UpdateView, FormView, DeleteView, CreateView
from reportlab.pdfgen import canvas

from abmci.services.notifications import push_inapp_notification
from fidele.models import Fidele, Department, Permanence, Eglise, ProblemeParticulier, Fonction, MembreType, \
    TransferHistory, Notification, UserProfileCompletion, AccountDeletionRequest, Donation, DonationCategory, \
    ProblemCategory, ProblemReport, ProblemAction, NotificationUser
from fidele.form import PermanenceForm, FideleUpdateForm, FideleTransferForm, ProfileCompletionForm, ConfirmDeleteForm, \
    ProblemReminderForm, ProblemStatusForm, ProblemAssignForm, ProblemCommentForm
from event.models import ParticipationEvenement
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, Count, Case, When, BooleanField, Value, DateField, F
# Notifications in-app : l'état lu/non lu est porté par NotificationUser (Notification n'a pas de champ user)
@login_required
def all_notifications(request):
    notifications = (NotificationUser.objects.filter(user=request.user)
                     .select_related('notification').order_by('-created_at')[:200])
    return render(request, 'notifications/all.html', {'notifications': notifications})


@login_required
def mark_read(request, pk):
    entry = get_object_or_404(NotificationUser, pk=pk, user=request.user)
    if not entry.is_read:
        entry.is_read = True
        entry.read_at = timezone.now()
        entry.save(update_fields=['is_read', 'read_at'])
    next_url = request.GET.get('next')
    # Pas de redirection ouverte vers un domaine externe
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                                    require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('all')


@login_required
def mark_all_read(request):
    NotificationUser.objects.filter(user=request.user, is_read=False).update(is_read=True, read_at=timezone.now())
    return redirect('all')


class Politique(TemplateView):
    # context_object_name = 'politique'
    template_name = 'landing/politique.html'


class SaftyChildren(TemplateView):
    # context_object_name = 'politique'
    template_name = 'landing/safety-policy.html'


class HomePageView(StaffRequiredMixin, TemplateView):
    """
    Dashboard analytique d'Alliance Connect.
    - Filtres de période (semaine/mois/trimestre/semestre/année/personnalisé)
    - Statistiques sur sacrements, démographie, engagement
    - Séries temporelles (12 derniers mois) pour les charts
    - Insights automatiques (analyse intelligente des données)
    """
    login_url = 'login/'
    form_class = LoginForm
    template_name = "home/index.html"

    def get_context_data(self, **kwargs):
        from fidele.dashboard_stats import build_dashboard_context

        context = super().get_context_data(**kwargs)

        user_fidele = getattr(self.request.user, 'fidele', None)
        eglise = getattr(user_fidele, 'eglise', None) if user_fidele else None

        context.update(build_dashboard_context(self.request, eglise=eglise))

        # Compat ascendante : laisse les anciens noms de variables disponibles
        kpis = context['kpis_main']
        context.setdefault('nombre_membres',    kpis['membres_actifs']['value'])
        context.setdefault('nombre_evenements', 0)
        context.setdefault('total_dons',        kpis['dons']['value'])
        context.setdefault('membres',           context['membres_recents'])
        context.setdefault('activity_recent',   context['activity'])
        context.setdefault('chart_labels',     context['charts']['labels'])
        context.setdefault('chart_cumulative', context['charts']['membres_cum'])
        context.setdefault('chart_monthly',    context['charts']['baptemes'])  # legacy fallback
        return context


class _LegacyHomePageView_DEPRECATED(StaffRequiredMixin, TemplateView):
    """Conservé temporairement pour référence — ne plus utiliser."""
    template_name = "home/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from event.models import Evenement  # import local pour éviter les cycles

        # ============================================================
        # Périmètre — uniquement l'église du fidèle connecté si possible
        # ============================================================
        user_fidele = getattr(self.request.user, 'fidele', None)
        eglise = getattr(user_fidele, 'eglise', None) if user_fidele else None

        fideles_qs = Fidele.objects.all()
        events_qs  = Evenement.objects.all()
        donations_qs = Donation.objects.filter(status='success')
        if eglise is not None:
            fideles_qs   = fideles_qs.filter(eglise=eglise)
            events_qs    = events_qs.filter(eglise=eglise)

        now   = timezone.now()
        today = now.date()
        first_of_month = today.replace(day=1)
        # Mois précédent
        last_month_end   = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        def _delta_pct(now_count: int, prev_count: int) -> str:
            """Variation en % vs précédent ; '+12 %' / '-3 %' / '—' si pas comparable."""
            if not prev_count:
                return f"+{now_count}" if now_count else ""
            diff = now_count - prev_count
            pct = round(diff / prev_count * 100)
            sign = '+' if pct >= 0 else ''
            return f"{sign}{pct} %"

        # ============================================================
        # KPI 1 — Visiteurs (membre = 0)
        # ============================================================
        visiteurs_total      = fideles_qs.filter(membre=0).count()
        visiteurs_this_month = fideles_qs.filter(membre=0, created_at__gte=first_of_month).count()
        visiteurs_last_month = fideles_qs.filter(
            membre=0, created_at__gte=last_month_start, created_at__lt=first_of_month
        ).count()

        # ============================================================
        # KPI 2 — Membres actifs (membre = 1)
        # ============================================================
        membres_actifs_total      = fideles_qs.filter(membre=1).count()
        membres_actifs_this_month = fideles_qs.filter(membre=1, created_at__gte=first_of_month).count()
        membres_actifs_last_month = fideles_qs.filter(
            membre=1, created_at__gte=last_month_start, created_at__lt=first_of_month
        ).count()

        # ============================================================
        # KPI 3 — Événements (à venir + en cours)
        # ============================================================
        events_total     = events_qs.count()
        events_upcoming  = events_qs.filter(date_fin__gte=now).count()
        events_last_30   = events_qs.filter(date_debut__gte=now - timedelta(days=30)).count()
        events_prev_30   = events_qs.filter(
            date_debut__gte=now - timedelta(days=60),
            date_debut__lt=now - timedelta(days=30),
        ).count()

        # ============================================================
        # KPI 4 — Dons (mois en cours, statut success)
        # ============================================================
        dons_this_month = donations_qs.filter(created_at__gte=first_of_month).aggregate(
            total=Sum('amount')
        )['total'] or 0
        dons_last_month = donations_qs.filter(
            created_at__gte=last_month_start, created_at__lt=first_of_month
        ).aggregate(total=Sum('amount'))['total'] or 0

        context['kpis'] = {
            'visiteurs': {
                'value': visiteurs_total,
                'delta': _delta_pct(visiteurs_this_month, visiteurs_last_month),
            },
            'membres_actifs': {
                'value': membres_actifs_total,
                'delta': _delta_pct(membres_actifs_this_month, membres_actifs_last_month),
            },
            'evenements': {
                'value': events_total,
                'upcoming': events_upcoming,
                'delta': _delta_pct(events_last_30, events_prev_30),
            },
            'dons_mois': {
                'value': f"{int(dons_this_month):,}".replace(',', ' '),
                'delta': _delta_pct(int(dons_this_month), int(dons_last_month)),
            },
        }

        # ============================================================
        # Chart : croissance cumulée des fidèles sur 12 mois
        # ============================================================
        labels   = []
        cumulative = []
        monthly  = []
        # Démarre 12 mois en arrière (incluant le mois courant)
        cursor = first_of_month
        # On remonte de 11 mois pour obtenir 12 points
        from calendar import monthrange
        months = []
        for i in range(11, -1, -1):
            # Calcul du premier jour du mois "courant - i"
            year  = first_of_month.year
            month = first_of_month.month - i
            while month <= 0:
                month += 12
                year  -= 1
            months.append((year, month))

        labels_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
                     'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
        for (y, m) in months:
            month_start = date(y, m, 1)
            # premier jour du mois suivant
            if m == 12:
                next_start = date(y + 1, 1, 1)
            else:
                next_start = date(y, m + 1, 1)

            cum = fideles_qs.filter(created_at__lt=next_start).count()
            mon = fideles_qs.filter(
                created_at__gte=month_start,
                created_at__lt=next_start,
            ).count()
            labels.append(labels_fr[m - 1])
            cumulative.append(cum)
            monthly.append(mon)

        context['chart_labels']     = labels
        context['chart_cumulative'] = cumulative
        context['chart_monthly']    = monthly

        # ============================================================
        # Liste des 6 fidèles les plus récents
        # ============================================================
        context['membres'] = (
            fideles_qs.select_related('user').order_by('-created_at')[:6]
        )

        # ============================================================
        # Activité récente (max 6 items, mélange membres / events / dons)
        # ============================================================
        activity = []
        for f in fideles_qs.order_by('-created_at')[:3]:
            activity.append({
                'kind': 'fidele',
                'tone': 'emerald',
                'icon': 'user-plus',
                'title': f"Nouveau fidèle : {f}",
                'when':  f.created_at,
            })
        for e in events_qs.order_by('-date_debut')[:3]:
            activity.append({
                'kind': 'event',
                'tone': 'brand',
                'icon': 'calendar-check',
                'title': f"Événement : {e.titre}" if hasattr(e, 'titre') else "Événement",
                'when':  e.date_debut,
            })
        for d in donations_qs.order_by('-created_at')[:3]:
            activity.append({
                'kind': 'donation',
                'tone': 'amber',
                'icon': 'hand-coins',
                'title': f"Don de {d.amount:,} {d.currency}".replace(',', ' '),
                'when':  d.created_at,
            })
        # Tri global décroissant + 6 premiers
        activity.sort(key=lambda x: x['when'], reverse=True)
        context['activity_recent'] = activity[:6]

        # ============================================================
        # Compat ascendante avec l'ancien template (au cas où)
        # ============================================================
        context['nombre_membres']    = membres_actifs_total or fideles_qs.count()
        context['nombre_evenements'] = events_total
        context['total_dons']        = context['kpis']['dons_mois']['value']
        context['direction']         = Department.objects.count()

        return context


class DirectionDetailView(StaffRequiredMixin, DetailView):
    """
    Vue détail d'une direction avec tabs : Membres / Réunions / Présences services.
    """
    model = Department
    template_name = "home/direction_view.html"
    context_object_name = 'directions'

    def get_context_data(self, **kwargs):
        from fidele.models import Service, ParticipationService, OuvrierPermanence
        from django.db.models import Count, Q
        context = super().get_context_data(**kwargs)
        direction = get_object_or_404(Department, pk=self.kwargs['pk'])
        members_qs = Fidele.objects.filter(departement=direction).select_related('user')

        # ===== Membres
        context['nombre_membres'] = members_qs.count()
        context['fideles']        = members_qs.order_by('user__last_name')

        # ===== Réunions / programme (Permanence + OuvrierPermanence)
        permanences = (Permanence.objects.filter(direction=direction)
                                          .select_related('event', 'auteur')
                                          .order_by('-add_date'))
        context['permanence']       = permanences          # compat ascendante
        context['reunions']         = permanences
        context['ouvriers_assigns'] = (OuvrierPermanence.objects
                                       .filter(programme__direction=direction)
                                       .select_related('ouvrier', 'ouvrier__user', 'poste', 'programme', 'programme__event')
                                       .order_by('-date'))

        # Programme à venir (reposant sur l'event lié si présent)
        upcoming = []
        for p in permanences:
            if p.event and getattr(p.event, 'date_debut', None):
                if p.event.date_debut >= timezone.now():
                    upcoming.append(p)
        context['programme_a_venir'] = upcoming[:10]

        # ===== Présences aux services
        services = (Service.objects.filter(participants__in=members_qs)
                                    .annotate(
                                        nb_participants=Count('participations',
                                            filter=Q(participations__fidele__in=members_qs), distinct=True),
                                        nb_presents=Count('participations',
                                            filter=Q(participations__fidele__in=members_qs,
                                                     participations__presence=True), distinct=True),
                                    )
                                    .distinct()
                                    .order_by('-date'))
        context['services'] = services

        # Stats globales présences
        nb_part_total = ParticipationService.objects.filter(fidele__in=members_qs).count()
        nb_present_total = ParticipationService.objects.filter(fidele__in=members_qs, presence=True).count()
        context['stats_presence'] = {
            'total_participations': nb_part_total,
            'total_presents':       nb_present_total,
            'taux_presence':        round(nb_present_total / nb_part_total * 100) if nb_part_total else 0,
        }

        # ===== Form pour ajouter un ouvrier à la permanence
        context['permanence_form'] = PermanenceForm(self.request.GET, initial={'direction': direction})
        context['permanence_form'].fields['ouvrier'].queryset = members_qs

        return context


@staff_required
def permanencecreate(request, pk):
    if request.method == 'POST':
        form = PermanenceForm(request.POST)
        if form.is_valid():
            ouvrier_permanence_instance = form.save(commit=False)

            # Vérifier si une instance de Permanence existe déjà pour cet événement
            event_instance = form.cleaned_data['event']
            existing_permanence_instance = Permanence.objects.filter(event=event_instance).first()

            if existing_permanence_instance:
                ouvrier_permanence_instance.programme = existing_permanence_instance
            else:
                # Créer une nouvelle instance de Permanence seulement si elle n'existe pas
                permanence_instance = Permanence.objects.create(
                    titre='Programme',
                    event=event_instance,
                    auteur=request.user.fidele,
                    direction=request.user.fidele.departement,
                )
                ouvrier_permanence_instance.programme = permanence_instance

            ouvrier_permanence_instance.save()

            messages.success(request, "L'ouvrier a été ajouté avec succes")
            return redirect('direction', pk=pk)
        else:
            messages.error(request, "désolé la permanence ne peut etre creer ")
    else:
        # Handle the case when the request method is not POST
        return redirect('direction', pk=pk)


class SuivieFideleListView(StaffRequiredMixin, ListView):
    model = Fidele
    template_name = "fidele/suivie_fidele.html"
    context_object_name = "membres"
    paginate_by = 25

    def get_queryset(self):
        # Récupérer l'église de l'utilisateur connecté
        user_eglise = self.request.user.fidele.eglise
        queryset = Fidele.objects.filter(eglise=user_eglise).select_related(
            'user', 'fonction', 'eglise'
        ).prefetch_related('problemes')

        # Appliquer les filtres
        queryset = self.apply_filters(queryset)

        # Annoter avec des informations utiles
        queryset = queryset.annotate(
            nb_problemes=Count('problemes'),
            est_recent=Case(
                When(date_entree__gte=timezone.now().date() - timedelta(days=21), then=1),
                default=0,
                output_field=IntegerField()
            )
        )

        return queryset.order_by('-date_entree')

    def apply_filters(self, queryset):
        # Filtre par statut
        statut = self.request.GET.get('statut')
        if statut:
            statut_map = {
                'Visiteur': 0,
                'Membre actif': 1,
                'FISS': 2,
                'Sympathisant': 3
            }
            queryset = queryset.filter(membre=statut_map.get(statut, 0))

        # Filtre par période d'entrée
        date_range = self.request.GET.get('date_range')
        if date_range:
            try:
                start_date, end_date = date_range.split(' au ')
                queryset = queryset.filter(
                    date_entree__gte=start_date,
                    date_entree__lte=end_date
                )
            except:
                pass

        # Filtre par baptême
        bapteme = self.request.GET.get('bapteme')
        if bapteme == 'baptise':
            queryset = queryset.exclude(date_bapteme__isnull=True)
        elif bapteme == 'non_baptise':
            queryset = queryset.filter(date_bapteme__isnull=True)

        # Filtre par recherche texte
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(user__email__icontains=search_query)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()

        # Statistiques pour les cartes
        total_visiteurs = queryset.count()
        nouveaux_visiteurs = queryset.filter(est_recent=1).count()
        baptises = queryset.exclude(date_bapteme__isnull=True).count()
        total_problemes = ProblemeParticulier.objects.filter(fidele__in=queryset).count()

        context.update({
            'total_visiteurs': total_visiteurs,
            'nouveaux_visiteurs': nouveaux_visiteurs,
            'baptises': baptises,
            'total_problemes': total_problemes,
            'pourcentage_visiteurs': (
                    total_visiteurs / Fidele.objects.count() * 100) if Fidele.objects.count() > 0 else 0,
            'pourcentage_nouveaux': (nouveaux_visiteurs / total_visiteurs * 100) if total_visiteurs > 0 else 0,
            'pourcentage_baptises': (baptises / total_visiteurs * 100) if total_visiteurs > 0 else 0,
            'pourcentage_avec_problemes': (total_problemes / total_visiteurs * 100) if total_visiteurs > 0 else 0,
            'date_debut': timezone.now().date() - timedelta(days=30),
            'date_fin': timezone.now().date(),
        })

        return context


class FideleListView(StaffRequiredMixin, ListView):
    model = Fidele
    template_name = "fidele/fidele_list.html"
    context_object_name = "membres"
    paginate_by = 10

    def get_page_range(self, paginator, page_obj):
        """Génère une liste de pages à afficher dans la pagination."""
        num_pages = paginator.num_pages
        if num_pages <= 7:
            return range(1, num_pages + 1)
        elif page_obj.number <= 4:
            return range(1, 6)
        elif page_obj.number >= num_pages - 3:
            return range(num_pages - 4, num_pages + 1)
        else:
            return range(page_obj.number - 2, page_obj.number + 3)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()

        # Filtre par église
        eglise_id = self.request.GET.get('eglise_id')
        context['eglise_id'] = eglise_id
        context['eglise_selectionnee'] = Eglise.objects.filter(id=eglise_id).first() if eglise_id else None

        # Statistiques générales
        context['nombre_fideles'] = queryset.count()
        context['church'] = Eglise.objects.all()
        context['page_range'] = self.get_page_range(context['paginator'], context['page_obj'])

        # Préparation des données pour les graphiques
        self.prepare_chart_data(context, queryset)

        # Préparation des filtres avancés
        self.prepare_advanced_filters(context)

        return context

    def prepare_chart_data(self, context, queryset):
        """Prépare les données pour les graphiques statistiques."""
        # Statistiques démographiques
        context['stats'] = {
            'hommes': queryset.filter(sexe='Homme').count(),  # valeurs de SEXE_CHOICES
            'femmes': queryset.filter(sexe='Femme').count(),
            'nouveaux': queryset.filter(date_entree__gte=timezone.now() - timedelta(days=21)).count(),
            'baptises': queryset.exclude(date_bapteme=None).count(),
            'visiteurs': queryset.filter(membre=0).count(),
            'membres_actifs': queryset.filter(membre=1).count(),
            'fiss': queryset.filter(membre=2).count(),
        }

        # Répartition par âge
        age_ranges = [
            ('0-17', queryset.filter(birthdate__gte=timezone.now() - timedelta(days=365 * 18))),
            ('18-25', queryset.filter(birthdate__lt=timezone.now() - timedelta(days=365 * 18),
                                      birthdate__gte=timezone.now() - timedelta(days=365 * 26))),
            ('26-35', queryset.filter(birthdate__lt=timezone.now() - timedelta(days=365 * 26),
                                      birthdate__gte=timezone.now() - timedelta(days=365 * 36))),
            ('36-50', queryset.filter(birthdate__lt=timezone.now() - timedelta(days=365 * 36),
                                      birthdate__gte=timezone.now() - timedelta(days=365 * 51))),
            ('50+', queryset.filter(birthdate__lt=timezone.now() - timedelta(days=365 * 51))),
        ]
        context['age_distribution'] = [(label, qs.count()) for label, qs in age_ranges]

        # Répartition par statut
        context['status_distribution'] = [
            ('Visiteurs', context['stats']['visiteurs']),
            ('Membres actifs', context['stats']['membres_actifs']),
            ('FISS', context['stats']['fiss']),
            ('Sympathisants', queryset.filter(membre__isnull=True).count())
        ]

    def prepare_advanced_filters(self, context):
        """Prépare les données pour les filtres avancés."""
        context['departments'] = Department.objects.all()
        context['fonctions'] = Fonction.objects.all()
        context['type_membres'] = MembreType.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'user', 'eglise', 'departement', 'fonction', 'type_membre'
        )

        # Filtre par église
        eglise_id = self.request.GET.get('eglise_id')
        if eglise_id:
            queryset = queryset.filter(eglise_id=eglise_id)

        # Filtre par statut
        statut = self.request.GET.get('statut')
        if statut:
            if statut == 'visiteur':
                queryset = queryset.filter(membre=0)
            elif statut == 'actif':
                queryset = queryset.filter(membre=1)
            elif statut == 'fiss':
                queryset = queryset.filter(membre=2)

        # Filtre par département
        departement_id = self.request.GET.get('departement_id')
        if departement_id:
            queryset = queryset.filter(departement_id=departement_id)

        # Filtre par type de membre
        type_membre_id = self.request.GET.get('type_membre_id')
        if type_membre_id:
            queryset = queryset.filter(type_membre_id=type_membre_id)

        # Filtre par recherche
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(phone__icontains=search_query)
            )

        return queryset.order_by('user__last_name', 'user__first_name')


class FideleCreateView(StaffRequiredMixin, CreateView):
    model = Fidele
    template_name = "fidele/fidele_form.html"
    fields = [
        'birthdate', 'sexe', 'situation_matrimoniale', 'signe', 'nbr_enfants',
        'contry', 'phone', 'nationalite', 'eglise_origine',
        'date_entree', 'date_bapteme', 'type_bapteme', 'lieu_bapteme', 'profession',
        'entreprise', 'mensual_revenue', 'salary_currency', 'marie_a', 'pere', 'mere',
        'type_membre', 'membre', 'location', 'departement', 'fonction', 'eglise',
        'famille_alliance', 'photo'
    ]
    # permission_required = 'fidele.can_edit_employee'
    success_url = reverse_lazy('membres')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Fidele.user est obligatoire : on collecte l'identité pour créer le compte associé
        identity = {
            'first_name': forms.CharField(label="Prénom", max_length=150),
            'last_name': forms.CharField(label="Nom", max_length=150),
            'email': forms.EmailField(label="E-mail"),
        }
        form.fields = {**identity, **form.fields}
        return form

    def form_valid(self, form):
        User = get_user_model()
        data = form.cleaned_data
        if User.objects.filter(email__iexact=data['email']).exists():
            form.add_error('email', "Un compte existe déjà avec cet e-mail.")
            return self.form_invalid(form)

        with transaction.atomic():
            user = User.objects.create_user(
                username=generate_unique_username([data['first_name'], data['last_name'], data['email'], 'user']),
                email=data['email'], first_name=data['first_name'], last_name=data['last_name'],
            )
            user.set_unusable_password()
            user.save(update_fields=['password'])
            # La fiche est créée par le signal post_save create_fidele : on la complète avec le formulaire
            fidele, _ = Fidele.objects.get_or_create(user=user)
            construct_instance(form, fidele, fields=self.fields)
            fidele.save()
        self.object = fidele
        messages.success(self.request, f"Fidèle {self.object} créé avec succès!")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Ajouter un nouveau fidèle"
        return context


class FideleDeleteView(StaffRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = Fidele
    template_name = "fidele/fidele_confirm_delete.html"
    permission_required = 'fidele.can_edit_employee'
    success_url = reverse_lazy('membres')

    def form_valid(self, form):
        # Django ≥ 4 : DeleteView passe par form_valid (delete() n'est plus appelée sur POST)
        messages.success(self.request, "Fidèle supprimé avec succès!")
        return super().form_valid(form)


class FideleTransferView(StaffRequiredMixin, PermissionRequiredMixin, FormView):
    template_name = "fidele/fidele_transfer.html"
    form_class = FideleTransferForm
    permission_required = 'fidele.can_edit_employee'
    success_url = reverse_lazy('membres')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fidele_id = self.kwargs.get('pk')
        context['fidele'] = get_object_or_404(Fidele, pk=fidele_id)
        return context

    def form_valid(self, form):
        fidele_id = self.kwargs.get('pk')
        fidele = get_object_or_404(Fidele, pk=fidele_id)
        nouvelle_eglise = form.cleaned_data['nouvelle_eglise']
        motif = form.cleaned_data['motif']

        ancienne_eglise = fidele.eglise
        with transaction.atomic():
            # Historique avant transfert
            TransferHistory.objects.create(
                fidele=fidele,
                ancienne_eglise=ancienne_eglise,
                nouvelle_eglise=nouvelle_eglise,
                effectue_par=self.request.user,
                motif=motif
            )

            # Mise à jour du fidèle
            fidele.eglise = nouvelle_eglise
            fidele.save()

            # Notification (l'ancienne église est capturée avant la mise à jour)
            self.send_transfer_notification(fidele, ancienne_eglise, nouvelle_eglise, motif)

        messages.success(self.request, f"{fidele} a été transféré à {nouvelle_eglise} avec succès!")
        return super().form_valid(form)

    @staticmethod
    def _emails_responsables(eglise):
        # Eglise n'a pas de relation « responsables » : on cible les fidèles de l'église ayant le rôle PASTEUR
        if eglise is None:
            return []
        return list(Fidele.objects.filter(eglise=eglise, roles__code="PASTEUR")
                    .exclude(user__email="").values_list("user__email", flat=True).distinct())

    def send_transfer_notification(self, fidele, ancienne_eglise, nouvelle_eglise, motif):
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or None
        # Notification à l'ancienne église
        for email in self._emails_responsables(ancienne_eglise):
            send_mail(
                subject=f"Transfert de {fidele}",
                message=f"{fidele} a été transféré à {nouvelle_eglise}. Motif: {motif}",
                from_email=from_email,
                recipient_list=[email],
                fail_silently=True,
            )

        # Notification à la nouvelle église
        for email in self._emails_responsables(nouvelle_eglise):
            send_mail(
                subject=f"Nouveau fidèle transféré: {fidele}",
                message=f"{fidele} a été transféré dans votre église. Motif: {motif}",
                from_email=from_email,
                recipient_list=[email],
                fail_silently=True,
            )

        # Notification au fidèle lui-même
        if fidele.user.email:
            send_mail(
                subject=f"Votre transfert à {nouvelle_eglise}",
                message=f"Vous avez été transféré à {nouvelle_eglise}. Motif: {motif}",
                from_email=from_email,
                recipient_list=[fidele.user.email],
                fail_silently=True,
            )


class VieDeLEgliseListView(StaffRequiredMixin, ListView):
    model = Fidele
    template_name = "home/vie_eglise.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f = get_object_or_404(Fidele, pk=self.kwargs["pk"])
        context["fidele_detail"] = f
        context["fidele"] = f  # alias pour les nouveaux templates
        return context

    def get_queryset(self):
        fidele_instance = get_object_or_404(Fidele, pk=self.kwargs["pk"])
        participations = ParticipationEvenement.objects.filter(fidele=fidele_instance)
        evenements_participes = [participation.evenement for participation in participations]
        return evenements_participes


class EngagementListView(StaffRequiredMixin, ListView):
    model = Fidele
    template_name = "home/engagement.html"

    def get_queryset(self):
        # Sans surcharge, la ListView renvoyait tous les fidèles de la base dans l'onglet
        return Fidele.objects.filter(pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f = get_object_or_404(Fidele, pk=self.kwargs["pk"])
        context["fidele_detail"] = f
        context["fidele"] = f  # alias pour les nouveaux templates
        return context


class StatutSocialListView(StaffRequiredMixin, ListView):
    model = Fidele
    template_name = "home/statutsocia.html"

    def get_queryset(self):
        # Sans surcharge, la ListView renvoyait tous les fidèles de la base dans l'onglet
        return Fidele.objects.filter(pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f = get_object_or_404(Fidele, pk=self.kwargs["pk"])
        context["fidele_detail"] = f
        context["fidele"] = f  # alias pour les nouveaux templates
        fidele_instance = get_object_or_404(Fidele, pk=self.kwargs["pk"])
        context["frere"] = fidele_instance.frere.all()
        context["soeur"] = fidele_instance.soeur.all()
        context["enfant"] = Fidele.objects.filter(pere=fidele_instance)
        context["enfantnbr"] = Fidele.objects.filter(pere=fidele_instance).count()
        return context

    # def get_queryset(self):
    #     fidele_instance = get_object_or_404(Fidele, pk=self.kwargs["pk"])
    #     enfants = Fidele.objects.filter(pere=fidele_instance)
    #     return enfants
    # #
    # def get_queryset(self):
    #     fidele_instance = get_object_or_404(Fidele, pk=self.kwargs["pk"])
    #     freres = fidele_instance.frere.all()
    #     soeur = fidele_instance.soeur.all()
    #     return freres, soeur


class MessagerieListView(StaffRequiredMixin, ListView):
    model = Fidele
    template_name = "home/messagerie.html"

    def get_queryset(self):
        # Sans surcharge, la ListView renvoyait tous les fidèles de la base dans l'onglet
        return Fidele.objects.filter(pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f = get_object_or_404(Fidele, pk=self.kwargs["pk"])
        context["fidele_detail"] = f
        context["fidele"] = f  # alias pour les nouveaux templates
        return context


class FideleDetailView(StaffRequiredMixin, DetailView):
    model = Fidele
    template_name = "fidele/fidele_detail.html"
    context_object_name = "fidele_detail"

    def get_absolute_url(self):
        return reverse("list_fidele")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fidele = self.object

        # Ajouter le nombre d'enfants et la liste des enfants au contexte
        # context['nombre_enfants'] = self.object.enfant.count()

        context['problemes'] = ProblemeParticulier.objects.filter(fidele=fidele)

        return context


class FideleUpdateView(StaffRequiredMixin, UpdateView):
    model = Fidele
    template_name = "fidele/fidele_update.html"
    form_class = FideleUpdateForm
    context_object_name = "fidele_detail"

    def get_object(self):
        # Récupère l'objet fidele à partir de l'URL
        pk = self.kwargs.get("pk")
        return Fidele.objects.get(pk=pk)

    def form_valid(self, form):
        # Logique pour le cas où le formulaire est valide
        messages.success(self.request, 'Successfully updated!')

        return super().form_valid(form)

    def form_invalid(self, form):
        # Logique pour le cas où le formulaire n'est pas valide
        messages.error(self.request, 'Form validation failed. Please check the form and try again.')
        error_message = form.errors.as_text()
        print(f'le message de non valid: {error_message}')
        return super().form_invalid(form)

    def get_success_url(self):
        pk = self.kwargs["pk"]
        messages.success(self.request, "Your Task has been registered successfully")

        return reverse("update", kwargs={"pk": pk}, )


@login_required
def complete_profile(request):
    try:
        profile = request.user.fidele
    except Fidele.DoesNotExist:
        profile = Fidele.objects.create(user=request.user)

    completion, _ = UserProfileCompletion.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = ProfileCompletionForm(
            request.POST,
            request.FILES,
            instance=profile,
            step=completion.current_step
        )

        if form.is_valid():
            form.save()

            if completion.current_step < 5:
                completion.current_step += 1
                completion.save()
                return redirect(reverse('complete_profile') + f'?step={completion.current_step}')
            else:
                completion.is_complete = True
                completion.save()
                return redirect('profile_complete')
    else:
        step = request.GET.get('step', completion.current_step)
        form = ProfileCompletionForm(
            instance=profile,
            step=step
        )

    progress = completion.current_step * 20  # 5 étapes = 20% par étape

    context = {
        'form': form,
        'step': completion.current_step,
        'progress': progress,
        'step_data': {
            'title': form.step_title,
            'description': form.step_description
        },
        'total_steps': 5
    }

    return render(request, 'home/complete_profile.html', context)


@login_required
def profile_complete(request):
    return render(request, 'home/profile_complete.html')


def perform_user_full_deletion(user):
    """Ici on anonymise/supprime toutes les données applicatives liées à l'utilisateur,
       puis on supprime l’utilisateur lui-même."""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # TODO: anonymiser/supprimer données spécifiques (messages, posts, fichiers, logs…)
    # Exemple:
    # Post.objects.filter(author=user).delete()
    # FileUpload.objects.filter(owner=user).delete()
    # etc.

    # Enfin, suppression du user (CASCADE sur FK on_delete=models.CASCADE)
    user.delete()


def process_account_deletion_request(req_id):
    req = AccountDeletionRequest.objects.select_related("user").get(pk=req_id)
    if req.status not in ("requested", "failed"):
        return

    req.status = "processing"
    req.save(update_fields=["status"])

    if req.user is None:  # compte déjà supprimé par ailleurs
        req.status = "done"
        req.processed_at = timezone.now()
        req.save(update_fields=["status", "processed_at"])
        return

    user_pk = req.user.pk
    try:
        with transaction.atomic():
            perform_user_full_deletion(req.user)
        # La demande survit à la suppression (user → NULL) : on garde l'identifiant pour la traçabilité
        req.user = None
        req.status = "done"
        req.processed_at = timezone.now()
        req.notes = f"Compte utilisateur #{user_pk} supprimé."
        req.save(update_fields=["user", "status", "processed_at", "notes"])
    except Exception as e:
        req.status = "failed"
        req.notes = str(e)
        req.save(update_fields=["status", "notes"])
        raise


class AccountDeleteRequestView(LoginRequiredMixin, View):
    template_name = "landing/account_delete.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"form": ConfirmDeleteForm()})

    def post(self, request, *args, **kwargs):
        form = ConfirmDeleteForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        req = AccountDeletionRequest.objects.create(user=request.user, status="requested")
        # (optionnel) notifier l’équipe / l’utilisateur
        try:
            send_mail(
                subject="Demande de suppression de compte",
                message=f"Utilisateur #{request.user.pk} a demandé la suppression.",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[getattr(settings, "SUPPORT_EMAIL", "support@example.com")],
                fail_silently=True,
            )
        except Exception:
            pass

        # Déconnexion immédiate
        # perform_logout(request, "account_logout")  # allauth logout helper
        messages.success(request, "Votre demande de suppression a été enregistrée.")
        return redirect("account_delete_done")


# (B) Page "demande reçue"
class AccountDeleteDoneView(View):
    template_name = "account/account_delete_done.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)


class DonationListView(StaffRequiredMixin, ListView):
    model = Donation
    template_name = 'donations/donation_list.html'
    context_object_name = 'donations'
    paginate_by = 10

    _qs = None  # évite recalculs

    def get_base_queryset(self):
        user = self.request.user
        # Par défaut: uniquement les dons de l’utilisateur courant
        qs = Donation.objects.select_related('category')
        if user.is_staff and self.request.GET.get('all') == '1':
            # Admin + ?all=1 -> tout voir
            return qs
        return qs.filter(user=user)

    def get_queryset(self):
        if self._qs is not None:
            return self._qs

        qs = self.get_base_queryset()

        # --- Filtres ---
        status = (self.request.GET.get('status') or '').strip()
        category = (self.request.GET.get('category') or '').strip()  # code ou id
        date_from = parse_date(self.request.GET.get('date_from') or '')
        date_to = parse_date(self.request.GET.get('date_to') or '')

        if status:
            qs = qs.filter(status=status)

        if category:
            if category.isdigit():
                qs = qs.filter(category_id=int(category))
            else:
                qs = qs.filter(category__code=category)

        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        self._qs = qs.order_by('-created_at')
        return self._qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.get_queryset()

        # Agrégats pour stats
        aggs = qs.aggregate(
            total_amount=Sum('amount'),
            success_amount=Sum('amount', filter=Q(status='success')),
            pending_amount=Sum('amount', filter=Q(status='pending')),
            success_count=Count('id', filter=Q(status='success')),
            pending_count=Count('id', filter=Q(status='pending')),
            failed_count=Count('id', filter=Q(status='failed')),
        )

        ctx['total_amount'] = aggs['total_amount'] or 0
        ctx['success_amount'] = aggs['success_amount'] or 0
        ctx['pending_amount'] = aggs['pending_amount'] or 0
        ctx['successful_count'] = aggs['success_count'] or 0
        ctx['pending_count'] = aggs['pending_count'] or 0
        ctx['failed_count'] = aggs['failed_count'] or 0

        # Filtres pour le template
        ctx['categories'] = DonationCategory.objects.all().order_by('name')
        ctx['current_filters'] = {
            'status': self.request.GET.get('status', ''),
            'category': self.request.GET.get('category', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }

        # Si le champ 'status' n’a pas de choices définis sur le modèle,
        # on fournit un fallback lisible.
        status_field = Donation._meta.get_field('status')
        choices = getattr(status_field, 'choices', None)
        ctx['status_choices'] = choices or (
            ('pending', 'En attente'),
            ('success', 'Réussi'),
            ('failed', 'Échoué'),
            ('abandoned', 'Abandonné'),
        )

        # Pour l’admin: savoir si “all=1” est actif
        ctx['showing_all'] = self.request.user.is_staff and self.request.GET.get('all') == '1'
        return ctx


class DonationDetailView(StaffRequiredMixin, DetailView):
    model = Donation
    template_name = 'donations/donation_detail.html'
    context_object_name = 'donation'


def add_comment(problem: ProblemReport, author: Fidele | None, message: str):
    with transaction.atomic():
        ProblemAction.objects.create(
            problem=problem, author=author, type=ProblemAction.Type.COMMENT, message=message
        )
        problem.updated_at = timezone.now()
        problem.save(update_fields=["updated_at"])


def assign_to(problem: ProblemReport, author: Fidele | None, assignee: Fidele):
    old_id = problem.assignee_id
    if old_id == assignee.id:
        return
    with transaction.atomic():
        problem.assignee = assignee
        problem.save(update_fields=["assignee", "updated_at"])
        ProblemAction.objects.create(
            problem=problem, author=author, type=ProblemAction.Type.ASSIGN,
            meta={"old_assignee_id": old_id, "new_assignee_id": assignee.id}
        )


def update_status(problem: ProblemReport, author: Fidele | None, new_status: str):
    old = problem.status
    if old == new_status:
        return
    with transaction.atomic():
        problem.status = new_status
        if new_status == ProblemReport.Status.RESOLVED:
            problem.resolved_at = timezone.now()
        problem.save(update_fields=["status", "resolved_at", "updated_at"])
        ProblemAction.objects.create(
            problem=problem, author=author, type=ProblemAction.Type.STATUS,
            meta={"old": old, "new": new_status}
        )


def notify_parties(problem: ProblemReport, title: str, body: str, data: dict):
    """Notifie reporter + assignee + watchers (sans doublons, sauf auteur de l’action)."""
    user_ids = set()
    if problem.reporter_id:
        user_ids.add(problem.reporter.user_id if hasattr(problem.reporter, "user_id") else problem.reporter.id)
    if problem.assignee_id:
        user_ids.add(problem.assignee.user_id if hasattr(problem.assignee, "user_id") else problem.assignee.id)
    for f in problem.watchers.all().only("id", "user_id"):
        user_ids.add(f.user_id if hasattr(f, "user_id") else f.id)

    # Notification in-app + push (le modèle Notification n'a pas de champ user : voir NotificationUser)
    push_inapp_notification(user_ids, type=data.get("type", "PROBLEM"), title=title, body=body, data=data)


def build_pdf_report(problem: ProblemReport) -> bytes:
    """Exemple minimal ReportLab (rapide). Remplace par WeasyPrint si tu veux du HTML/CSS."""
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.setTitle(f"Rapport - {problem.title}")
    y = 800
    c.drawString(40, y, f"Rapport de traitement - {problem.title}")
    y -= 30
    c.drawString(40, y,
                 f"Eglise: {problem.eglise_id} | Catégorie: {problem.category} | Sévérité: {problem.get_severity_display()}")
    y -= 20
    c.drawString(40, y,
                 f"Statut: {problem.get_status_display()} | Créé: {problem.created_at.strftime('%Y-%m-%d %H:%M')}")
    y -= 40
    c.drawString(40, y, "Historique :")
    y -= 20
    for act in problem.actions.select_related("author").order_by("created_at"):
        msg = act.message[:90].replace("\n", " ") if act.message else ""
        who = f"{getattr(act.author, 'id', '—')}"
        c.drawString(50, y, f"- {act.created_at:%Y-%m-%d %H:%M} [{act.type}] par {who} | {msg}")
        y -= 18
        if y < 80:
            c.showPage();
            y = 800
    c.showPage()
    c.save()
    return buf.getvalue()


def pdf_response(problem: ProblemReport) -> FileResponse:
    content = build_pdf_report(problem)
    return FileResponse(BytesIO(content), as_attachment=True, filename=f"rapport-probleme-{problem.pk}.pdf")


class ProblemTreatView(StaffRequiredMixin, PermissionRequiredMixin, DetailView):
    """Affiche le signalement + formulaires d’action"""
    permission_required = "fidele.can_view_all_problems"  # ou logique personnalisée
    model = ProblemReport
    template_name = "fidele/problems/problem_treat.html"
    context_object_name = "problem"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["comment_form"] = kwargs.get("comment_form") or ProblemCommentForm()
        ctx["assign_form"] = kwargs.get("assign_form") or ProblemAssignForm()
        ctx["status_form"] = kwargs.get("status_form") or ProblemStatusForm(initial={"status": self.object.status})
        ctx["reminder_form"] = kwargs.get("reminder_form") or ProblemReminderForm()
        return ctx


class ProblemTreatPostView(StaffRequiredMixin, PermissionRequiredMixin, View):
    """Traite les POST (comment, assign, status, rapport)"""
    permission_required = "fidele.can_view_all_problems"

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        problem = get_object_or_404(ProblemReport, pk=pk, is_deleted=False)

        action = request.POST.get("action")

        # Réponse / commentaire
        if action == "comment":
            form = ProblemCommentForm(request.POST)
            if form.is_valid():
                author = getattr(request.user, "fidele", None)  # adapte selon ta relation
                add_comment(problem, author, form.cleaned_data["message"])
                notify_parties(
                    problem,
                    title=_("Nouvelle réponse"),
                    body=form.cleaned_data["message"][:120],
                    data={"type": "PROBLEM_COMMENT", "problem_id": str(problem.id)},
                )
                messages.success(request, _("Réponse ajoutée."))
                return redirect(
                    problem.get_absolute_url() if hasattr(problem, "get_absolute_url") else reverse("treat",
                                                                                                    args=[problem.pk]))
            return ProblemTreatView.as_view()(request, pk=pk, comment_form=form)

        # Assignation
        if action == "assign":
            form = ProblemAssignForm(request.POST)
            if form.is_valid():
                assignee = get_object_or_404(Fidele, pk=form.cleaned_data["assignee_id"])
                author = getattr(request.user, "fidele", None)
                assign_to(problem, author, assignee)
                notify_parties(
                    problem,
                    title=_("Assignation"),
                    body=_("Le problème a été assigné."),
                    data={"type": "PROBLEM_ASSIGN", "problem_id": str(problem.id), "assignee_id": str(assignee.id)},
                )
                messages.success(request, _("Assigné avec succès."))
                return redirect(reverse("treat", args=[problem.pk]))
            return ProblemTreatView.as_view()(request, pk=pk, assign_form=form)

        # Changement de statut
        if action == "status":
            form = ProblemStatusForm(request.POST)
            if form.is_valid():
                author = getattr(request.user, "fidele", None)
                update_status(problem, author, form.cleaned_data["status"])
                notify_parties(
                    problem,
                    title=_("Statut mis à jour"),
                    body=_("Le statut du problème a été mis à jour."),
                    data={"type": "PROBLEM_STATUS", "problem_id": str(problem.id),
                          "status": form.cleaned_data["status"]},
                )
                messages.success(request, _("Statut mis à jour."))
                return redirect(reverse("treat", args=[problem.pk]))
            return ProblemTreatView.as_view()(request, pk=pk, status_form=form)

        # Générer un rapport PDF
        if action == "report":
            return pdf_response(problem)

        # Déclencher/paramétrer un rappel (stockage coté session ou profil)
        if action == "reminder":
            form = ProblemReminderForm(request.POST)
            if form.is_valid():
                request.session["problem_reminder_hours"] = form.cleaned_data["delay_hours"]
                messages.success(request, _("Délai de rappel défini."))
                return redirect(reverse("treat", args=[problem.pk]))
            return ProblemTreatView.as_view()(request, pk=pk, reminder_form=form)

        messages.error(request, _("Action inconnue."))
        return redirect(reverse("treat", args=[problem.pk]))


class ProblemReportListView(StaffRequiredMixin, PermissionRequiredMixin, ListView):
    model = ProblemReport
    permission_required = 'fidele.view_problemreport'
    template_name = 'fidele/problems/problem_list.html'
    context_object_name = 'problems'
    paginate_by = 25

    def _base_queryset(self):
        qs = ProblemReport.objects.filter(is_deleted=False)

        # Limitation par église si l'utilisateur n'a pas le droit "voir tout"
        if not self.request.user.has_perm('fidele.can_view_all_problems'):
            # éviter AttributeError si pas de fidèle lié
            fid = getattr(self.request.user, 'fidele', None)
            if fid and fid.eglise_id:
                qs = qs.filter(eglise=fid.eglise_id)
            else:
                qs = qs.none()

        # 👉 Annotation "is_overdue" (en base) pour filtrage/tri/agrégations
        today = timezone.localdate()
        qs = qs.annotate(
            is_overdue_db=Case(
                When(
                    Q(due_date__isnull=False) &
                    ~Q(status__in=[ProblemReport.Status.RESOLVED, ProblemReport.Status.CANCELED]) &
                    Q(due_date__lt=Value(today, output_field=DateField())),
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )

        return qs

    def get_queryset(self):
        qs = self._base_queryset()

        # Filtres
        status = self.request.GET.get('status')
        if status in dict(ProblemReport.Status.choices):
            qs = qs.filter(status=status)

        severity = self.request.GET.get('severity')
        if severity in dict(ProblemReport.Severity.choices):
            qs = qs.filter(severity=severity)

        category = self.request.GET.get('category')
        if category and str(category).isdigit():
            qs = qs.filter(category_id=int(category))

        assignee = self.request.GET.get('assignee')
        if assignee and str(assignee).isdigit():
            qs = qs.filter(assignee_id=int(assignee))

        overdue = self.request.GET.get('overdue')
        if overdue == 'true':
            qs = qs.filter(is_overdue_db=True)
        elif overdue == 'false':
            qs = qs.filter(is_overdue_db=False)

        # Recherche plein texte simple
        search = self.request.GET.get('search')
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(resolution_notes__icontains=search) |
                Q(reporter__user__first_name__icontains=search) |
                Q(reporter__user__last_name__icontains=search)
            )

        return qs.select_related(
            'eglise', 'reporter', 'assignee', 'category'
        ).prefetch_related('watchers').order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Filtres disponibles
        context['status_choices'] = ProblemReport.Status.choices
        context['severity_choices'] = ProblemReport.Severity.choices
        context['categories'] = ProblemCategory.objects.filter(is_active=True)

        # Valeurs des filtres actuels
        context['current_filters'] = {
            'status': self.request.GET.get('status') or '',
            'severity': self.request.GET.get('severity') or '',
            'category': self.request.GET.get('category') or '',
            'assignee': self.request.GET.get('assignee') or '',
            'overdue': self.request.GET.get('overdue') or '',
            'search': self.request.GET.get('search') or '',
        }

        # Stats sur le même queryset filtré et annoté
        qs = self.get_queryset().only('id', 'status', 'severity')  # légère optimisation
        context['stats'] = {
            'total': qs.count(),
            'open': qs.filter(status=ProblemReport.Status.OPEN).count(),
            'in_progress': qs.filter(status=ProblemReport.Status.IN_PROGRESS).count(),
            'overdue': qs.filter(is_overdue_db=True).count(),
            'by_status': list(qs.values('status').annotate(count=Count('id')).order_by()),
            'by_severity': list(qs.values('severity').annotate(count=Count('id')).order_by()),
        }

        return context

class ProblemReportCreateView(StaffRequiredMixin, PermissionRequiredMixin, CreateView):
    model = ProblemReport
    permission_required = 'fidele.add_problemreport'
    template_name = 'fidele/problems/problem_form.html'
    fields = ['title', 'description', 'category', 'severity', 'due_date']

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Limiter les catégories aux actives
        form.fields['category'].queryset = ProblemCategory.objects.filter(is_active=True)
        return form

    def form_valid(self, form):
        form.instance.reporter = self.request.user.fidele
        form.instance.eglise = self.request.user.fidele.eglise
        messages.success(self.request, 'Signalement créé avec succès.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('problemreport_detail', kwargs={'pk': self.object.pk})


class ProblemReportDetailView(StaffRequiredMixin, PermissionRequiredMixin, DetailView):
    model = ProblemReport
    permission_required = 'fidele.view_problemreport'
    template_name = 'fidele/problems/problem_detail.html'
    context_object_name = 'problem'

    def get_queryset(self):
        queryset = ProblemReport.objects.filter(is_deleted=False)
        if not self.request.user.has_perm('fidele.can_view_all_problems'):
            queryset = queryset.filter(eglise=self.request.user.fidele.eglise)
        return queryset.select_related('eglise', 'reporter', 'assignee', 'category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        problem = self.object

        # Historique des modifications (si simple-history est installé)
        if hasattr(problem, 'history'):
            context['history'] = problem.history.all()[:10]

        # Fidèles disponibles pour l'assignation
        # context['available_assignees'] = problem.eglise.fideles.filter(
        #     user__is_active=True
        # ).select_related('user')

        # Watchers actuels
        context['watchers'] = problem.watchers.select_related('user').all()

        return context


class ProblemReportUpdateView(StaffRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = ProblemReport
    permission_required = 'fidele.change_problemreport'
    template_name = 'problems/problem_form.html'
    fields = ['title', 'description', 'category', 'severity', 'status', 'due_date', 'resolution_notes']

    def get_queryset(self):
        queryset = ProblemReport.objects.filter(is_deleted=False)
        if not self.request.user.has_perm('fidele.can_view_all_problems'):
            queryset = queryset.filter(eglise=self.request.user.fidele.eglise)
        return queryset

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Limiter les catégories aux actives
        form.fields['category'].queryset = ProblemCategory.objects.filter(is_active=True)

        # Pour les non-administrateurs, limiter les champs modifiables
        if not self.request.user.has_perm('fidele.can_assign_problem'):
            del form.fields['status']
            del form.fields['resolution_notes']

        return form

    def form_valid(self, form):
        # Si le statut passe à résolu, mettre à jour la date de résolution
        if form.instance.status == ProblemReport.Status.RESOLVED and not form.instance.resolved_at:
            form.instance.resolved_at = timezone.now()

        messages.success(self.request, 'Signalement modifié avec succès.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('problemreport_detail', kwargs={'pk': self.object.pk})


class ProblemReportDeleteView(StaffRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = ProblemReport
    permission_required = 'fidele.delete_problemreport'
    template_name = 'problems/problem_confirm_delete.html'

    def get_queryset(self):
        queryset = ProblemReport.objects.filter(is_deleted=False)
        if not self.request.user.has_perm('fidele.can_view_all_problems'):
            queryset = queryset.filter(eglise=self.request.user.fidele.eglise)
        return queryset

    def form_valid(self, form):
        # Soft delete au lieu de suppression physique. Depuis Django 4, DeleteView traite le POST dans
        # form_valid : l'ancienne surcharge de delete() n'était plus appelée et la ligne était supprimée.
        self.object.is_deleted = True
        self.object.save(update_fields=['is_deleted'])
        messages.success(self.request, 'Signalement supprimé avec succès.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse_lazy('problemreport_list')


# Vues spéciales pour l'assignation et le changement de statut
class ProblemReportAssignView(StaffRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = ProblemReport
    permission_required = 'fidele.can_assign_problem'
    template_name = 'problems/problem_assign.html'
    fields = ['assignee']

    def get_queryset(self):
        return ProblemReport.objects.filter(is_deleted=False)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Limiter les assignés aux fidèles de la même église
        problem = self.get_object()
        form.fields['assignee'].queryset = problem.eglise.fideles.filter(
            user__is_active=True
        )
        return form

    def form_valid(self, form):
        messages.success(self.request, 'Signalement assigné avec succès.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('problemreport_detail', kwargs={'pk': self.object.pk})


# Vue pour les rapports et statistiques
class ProblemReportStatsView(StaffRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = 'fidele.view_problemreport'
    template_name = 'fidele/problems/problem_stats.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Base queryset
        queryset = ProblemReport.objects.filter(is_deleted=False)
        if not self.request.user.has_perm('fidele.can_view_all_problems'):
            queryset = queryset.filter(eglise=self.request.user.fidele.eglise)

        # Statistiques générales
        context['stats'] = {
            'total': queryset.count(),
            'resolved': queryset.filter(status='DONE').count(),
            'overdue': queryset.filter(is_overdue=True).count(),
            'avg_resolution_time': self._calculate_avg_resolution_time(queryset),
        }

        # Par statut
        context['by_status'] = queryset.values('status').annotate(
            count=Count('id')
        ).order_by('status')

        # Par sévérité
        context['by_severity'] = queryset.values('severity').annotate(
            count=Count('id')
        ).order_by('severity')

        # Par catégorie
        context['by_category'] = queryset.values(
            'category__name'
        ).annotate(
            count=Count('id')
        ).order_by('category__name')

        # Évolution mensuelle
        context['monthly_trend'] = self._get_monthly_trend(queryset)

        return context

    def _calculate_avg_resolution_time(self, queryset):
        resolved = queryset.filter(
            status='DONE',
            resolved_at__isnull=False,
            created_at__isnull=False
        )

        if not resolved.exists():
            return None

        total_duration = sum(
            (problem.resolved_at - problem.created_at).total_seconds()
            for problem in resolved
        )

        return total_duration / resolved.count()

    def _get_monthly_trend(self, queryset):
        # Implémentation simplifiée pour les tendances mensuelles
        from django.db.models.functions import TruncMonth
        return queryset.annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            count=Count('id')
        ).order_by('month')[:12]


class ProblemReportChangeStatusView(StaffRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = ProblemReport
    permission_required = 'fidele.can_assign_problem'
    template_name = 'problems/problem_change_status.html'
    fields = ['status', 'resolution_notes']

    def get_queryset(self):
        return ProblemReport.objects.filter(is_deleted=False)

    def form_valid(self, form):
        # Si le statut passe à résolu, mettre à jour la date de résolution
        if form.instance.status == ProblemReport.Status.RESOLVED and not form.instance.resolved_at:
            form.instance.resolved_at = timezone.now()

        messages.success(self.request, 'Statut modifié avec succès.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('problemreport_detail', kwargs={'pk': self.object.pk})
