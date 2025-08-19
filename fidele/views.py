from collections import defaultdict
from datetime import timedelta

from allauth.account.forms import LoginForm
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q, Case, When, IntegerField
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, ListView, DetailView, UpdateView, FormView, DeleteView, CreateView
from fidele.models import Fidele, Department, Permanence, Eglise, ProblemeParticulier, Fonction, MembreType, \
    TransferHistory, Notification, UserProfileCompletion, AccountDeletionRequest
from fidele.form import PermanenceForm, FideleUpdateForm, FideleTransferForm, ProfileCompletionForm, ConfirmDeleteForm
from event.models import ParticipationEvenement


@login_required
def all_notifications(request):
    notifications = Notification.objects.filter(recipient=request.user)
    return render(request, 'notifications/all.html', {'notifications': notifications})


@login_required
def mark_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notif.is_read = True
    notif.save()
    return redirect(request.GET.get('next') or 'notifs:all')


@login_required
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect('notifs:all')


class Politique(TemplateView):
    # context_object_name = 'politique'
    template_name = 'landing/politique.html'


class HomePageView(LoginRequiredMixin, TemplateView):
    login_url = 'login/'
    form_class = LoginForm
    template_name = "home/index.html"

    # def dispatch(self, request, *args, **kwargs):
    #     # Check if the user is authenticated. If not, redirect to the login page.
    #     if not request.user.is_authenticated:
    #         return redirect('login')
    #
    #     # Call the parent class's dispatch method for normal view processing.
    #     return super().dispatch(request, *args, **kwargs)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer le nombre total de membres
        context['nombre_membres'] = Fidele.objects.all().count()
        context['direction'] = Department.objects.all().count()

        return context


class DirectionDetailView(LoginRequiredMixin, DetailView):
    model = Department
    template_name = "home/direction_view.html"
    context_object_name = 'directions'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        direction = get_object_or_404(Department, pk=self.kwargs['pk'])

        # Récupérer le nombre total de membres
        context['nombre_membres'] = Fidele.objects.filter(departement=direction).count()
        context['permanence'] = Permanence.objects.filter(direction=direction)
        # context['permanence_form'] = PermanenceForm(self.request.GET)

        context['permanence_form'] = PermanenceForm(self.request.GET, initial={'direction': direction})
        # Filtrer le queryset des ouvriers en fonction du département sélectionné
        context['permanence_form'].fields['ouvrier'].queryset = Fidele.objects.filter(departement=direction)

        return context


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


class SuivieFideleListView(LoginRequiredMixin, ListView):
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
                Q(personal_mail__icontains=search_query)
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


class FideleListView(LoginRequiredMixin, ListView):
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
            'hommes': queryset.filter(sexe='M').count(),
            'femmes': queryset.filter(sexe='F').count(),
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
                Q(personal_mail__icontains=search_query) |
                Q(phone__icontains=search_query)
            )

        return queryset.order_by('user__last_name', 'user__first_name')


class FideleCreateView(LoginRequiredMixin, CreateView):
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
    # permission_required = 'home.can_edit_employee'
    success_url = reverse_lazy('fidele_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Fidèle {self.object} créé avec succès!")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Ajouter un nouveau fidèle"
        return context


class FideleDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = Fidele
    template_name = "fidele/fidele_confirm_delete.html"
    permission_required = 'home.can_edit_employee'
    success_url = reverse_lazy('fidele_list')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Fidèle supprimé avec succès!")
        return super().delete(request, *args, **kwargs)


class FideleTransferView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    template_name = "fidele/fidele_transfer.html"
    form_class = FideleTransferForm
    permission_required = 'home.can_edit_employee'
    success_url = reverse_lazy('fidele_list')

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

        with transaction.atomic():
            # Historique avant transfert
            TransferHistory.objects.create(
                fidele=fidele,
                ancienne_eglise=fidele.eglise,
                nouvelle_eglise=nouvelle_eglise,
                effectue_par=self.request.user,
                motif=motif
            )

            # Mise à jour du fidèle
            fidele.eglise = nouvelle_eglise
            fidele.save()

            # Notification
            self.send_transfer_notification(fidele, nouvelle_eglise, motif)

        messages.success(self.request, f"{fidele} a été transféré à {nouvelle_eglise} avec succès!")
        return super().form_valid(form)

    def send_transfer_notification(self, fidele, nouvelle_eglise, motif):
        # Notification à l'ancienne église
        if fidele.eglise:
            anciens_responsables = fidele.eglise.responsables.all()
            for responsable in anciens_responsables:
                send_mail(
                    subject=f"Transfert de {fidele}",
                    message=f"{fidele} a été transféré à {nouvelle_eglise}. Motif: {motif}",
                    from_email="noreply@votredomaine.com",
                    recipient_list=[responsable.email],
                    fail_silently=True,
                )

        # Notification à la nouvelle église
        nouveaux_responsables = nouvelle_eglise.responsables.all()
        for responsable in nouveaux_responsables:
            send_mail(
                subject=f"Nouveau fidèle transféré: {fidele}",
                message=f"{fidele} a été transféré dans votre église. Motif: {motif}",
                from_email="noreply@votredomaine.com",
                recipient_list=[responsable.email],
                fail_silently=True,
            )

        # Notification au fidèle lui-même
        if fidele.user.email:
            send_mail(
                subject=f"Votre transfert à {nouvelle_eglise}",
                message=f"Vous avez été transféré à {nouvelle_eglise}. Motif: {motif}",
                from_email="noreply@votredomaine.com",
                recipient_list=[fidele.user.email],
                fail_silently=True,
            )


class VieDeLEgliseListView(LoginRequiredMixin, ListView):
    model = Fidele
    template_name = "home/vie_eglise.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fidele_detail"] = Fidele.objects.get(pk=self.kwargs["pk"])
        return context

    def get_queryset(self):
        fidele_instance = get_object_or_404(Fidele, pk=self.kwargs["pk"])
        participations = ParticipationEvenement.objects.filter(fidele=fidele_instance)
        evenements_participes = [participation.evenement for participation in participations]
        return evenements_participes


class EngagementListView(LoginRequiredMixin, ListView):
    model = Fidele
    template_name = "home/engagement.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fidele_detail"] = Fidele.objects.get(pk=self.kwargs["pk"])
        return context


class StatutSocialListView(LoginRequiredMixin, ListView):
    model = Fidele
    template_name = "home/statutsocia.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fidele_detail"] = Fidele.objects.get(pk=self.kwargs["pk"])
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


class MessagerieListView(LoginRequiredMixin, ListView):
    model = Fidele
    template_name = "home/messagerie.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fidele_detail"] = Fidele.objects.get(pk=self.kwargs["pk"])
        return context


class FideleDetailView(LoginRequiredMixin, DetailView):
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


class FideleUpdateView(LoginRequiredMixin, UpdateView):
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

    try:
        with transaction.atomic():
            perform_user_full_deletion(req.user)
        req.status = "done"
        req.processed_at = timezone.now()
        req.save(update_fields=["status", "processed_at"])
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
