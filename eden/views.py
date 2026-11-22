from django.contrib import messages

from abmci.access import StaffRequiredMixin
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import UpdateView, DeleteView, CreateView, DetailView, ListView

from eden.models import Fiancailles, Mariage
from fidele.form import FiancaillesForm, MariageForm
from django.utils.translation import gettext_lazy as _


# Create your views here.

# ---------- Fiançailles ----------
class FiancaillesListView(StaffRequiredMixin, ListView):
    model = Fiancailles
    template_name = "eden/fiancailles_list.html"
    context_object_name = "fiancailles_list"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("homme__user", "femme__user", "conseiller")
        # Exemples de filtres : ?statut=En%20cours
        statut = self.request.GET.get("statut")
        if statut:
            qs = qs.filter(statut=statut)
        return qs.order_by("-date_demande")


class FiancaillesDetailView(StaffRequiredMixin, DetailView):
    model = Fiancailles
    template_name = "eden/fiancailles_detail.html"
    context_object_name = "fiancailles"


class FiancaillesCreateView(StaffRequiredMixin, CreateView):
    model = Fiancailles
    form_class = FiancaillesForm
    template_name = "eden/fiancailles_form.html"
    success_url = reverse_lazy("fiancailles-list")

    def form_valid(self, form):
        messages.success(self.request, _("Fiançailles créées avec succès."))
        return super().form_valid(form)


class FiancaillesUpdateView(StaffRequiredMixin, UpdateView):
    model = Fiancailles
    form_class = FiancaillesForm
    template_name = "eden/fiancailles_form.html"
    success_url = reverse_lazy("fiancailles-list")

    def form_valid(self, form):
        messages.success(self.request, _("Fiançailles mises à jour."))
        return super().form_valid(form)


class FiancaillesDeleteView(StaffRequiredMixin, DeleteView):
    model = Fiancailles
    template_name = "eden/confirm_delete.html"
    success_url = reverse_lazy("fiancailles-list")

    def form_valid(self, form):  # Django ≥ 4 : delete() n'est plus appelée sur POST
        messages.success(self.request, _("Fiançailles supprimées."))
        return super().form_valid(form)

# ---------- Mariage ----------
class MariageListView(StaffRequiredMixin, ListView):
    model = Mariage
    template_name = "eden/mariage_list.html"
    context_object_name = "mariage_list"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("officiant").prefetch_related("couple", "temoins")
        search = self.request.GET.get("q")
        if search:
            qs = qs.filter(lieu_mariage__icontains=search) | qs.filter(numero_acte__icontains=search)
        return qs.order_by("-date_mariage")


class MariageDetailView(StaffRequiredMixin, DetailView):
    model = Mariage
    template_name = "eden/mariage_detail.html"
    context_object_name = "mariage"


class MariageCreateView(StaffRequiredMixin, CreateView):
    model = Mariage
    form_class = MariageForm
    template_name = "eden/mariage_form.html"
    success_url = reverse_lazy("mariage-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        # le ManyToMany "couple" est géré par ModelForm, rien à faire
        messages.success(self.request, _("Mariage enregistré avec succès."))
        return response


class MariageUpdateView(StaffRequiredMixin, UpdateView):
    model = Mariage
    form_class = MariageForm
    template_name = "eden/mariage_form.html"
    success_url = reverse_lazy("mariage-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Mariage mis à jour."))
        return response


class MariageDeleteView(StaffRequiredMixin, DeleteView):
    model = Mariage
    template_name = "eden/confirm_delete.html"
    success_url = reverse_lazy("mariage-list")

    def form_valid(self, form):  # Django ≥ 4 : delete() n'est plus appelée sur POST
        messages.success(self.request, _("Mariage supprimé."))
        return super().form_valid(form)