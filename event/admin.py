import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin
from django.utils.translation import gettext_lazy as _
from event.models import Evenement, ParticipationEvenement, TypeEvent


# Register your models here.


# --------- Filtres personnalisés ---------
class EventStatusFilter(admin.SimpleListFilter):
    title = _("Statut")
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return (
            ("future", _("À venir")),
            ("ongoing", _("En cours")),
            ("past", _("Passé")),
        )

    def queryset(self, request, queryset):
        from django.utils import timezone
        now = timezone.now()
        if self.value() == "future":
            return queryset.filter(date_debut__gt=now)
        if self.value() == "ongoing":
            return queryset.filter(date_debut__lte=now, date_fin__gte=now)
        if self.value() == "past":
            return queryset.filter(date_fin__lt=now)
        return queryset


# --------- Inlines ---------
class ParticipationInline(admin.TabularInline):
    model = ParticipationEvenement
    extra = 0
    autocomplete_fields = ["fidele"]
    readonly_fields = ("date", "qr_code_scanned")
    fields = ("fidele", "commentaire", "qr_code_scanned", "date")
    ordering = ("-date",)


# --------- Actions ---------
@admin.action(description="Générer les occurrences pour les événements récurrents sélectionnés")
def action_generer_occurrences(modeladmin, request, queryset):
    """Crée des instances pour les séries (sans modèle supplémentaire)."""
    created = 0
    for event in queryset:
        if not event.is_recurrent:
            continue
        for occ in event.generate_events():
            # sauter l'événement source si la même date
            if occ.date_debut == event.date_debut and occ.date_fin == event.date_fin:
                continue
            # recopier les champs manquants (le default de code se régénère tout seul à save)
            occ.eglise = event.eglise
            occ.lieu = event.lieu
            occ.banner = event.banner  # réutilise le fichier si souhaité
            occ.save()
            created += 1
    modeladmin.message_user(request, f"{created} occurrence(s) créée(s).")


@admin.action(description="Exporter participants (CSV) des événements sélectionnés")
def action_export_participants_csv(modeladmin, request, queryset):
    """Export CSV de toutes les participations des événements sélectionnés."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="participants_events.csv"'
    writer = csv.writer(response)
    writer.writerow(["event_code", "event_title", "fidele_id", "fidele_nom", "fidele_prenom",
                     "phone", "date_participation", "qr_code_scanned"])

    parts = (ParticipationEvenement.objects
             .filter(evenement__in=queryset)
             .select_related("evenement", "fidele", "fidele__user")
             .order_by("evenement__code", "-date"))

    for p in parts:
        user = getattr(p.fidele, "user", None)
        prenom = getattr(user, "first_name", "") if user else ""
        nom = getattr(user, "last_name", "") if user else ""
        phone = getattr(p.fidele, "phone", "") or ""
        writer.writerow([
            p.evenement.code,
            p.evenement.titre,
            p.fidele_id,
            nom, prenom,
            phone,
            p.date.strftime("%Y-%m-%d %H:%M:%S"),
            "1" if p.qr_code_scanned else "0",
        ])
    return response


# --------- ModelAdmins ---------

@admin.register(TypeEvent)
class TypeEventAdmin(SimpleHistoryAdmin):
    list_display = ("name",)
    # IMPORTANT: provide search_fields (used by autocomplete)
    search_fields = ("name",)


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    list_display = (
        "titre", "code", "date_debut", "date_fin", "eglise", "type",
        "is_recurrent", "nombre_participants", "taux_participation_display",
        "qr_mini",
    )
    list_filter = (
        EventStatusFilter, "is_recurrent", "type", "eglise",
        ("date_debut", admin.DateFieldListFilter),
        ("date_fin", admin.DateFieldListFilter),
    )
    search_fields = (
        "titre", "code", "lieu", "description",
        "eglise__name", "type__name",
    )
    date_hierarchy = "date_debut"
    readonly_fields = ("code", "qr_preview", "taux_participation_display")
    inlines = [ParticipationInline]
    actions = [action_generer_occurrences, action_export_participants_csv]
    autocomplete_fields = ("eglise", "type")

    fieldsets = (
        (_("Infos principales"), {
            "fields": ("titre", "code", "eglise", "type", "lieu", "description"),
        }),
        (_("Dates"), {
            "fields": ("date_debut", "date_fin"),
        }),
        (_("Média"), {
            "fields": ("banner", "qr_preview"),
        }),
        (_("Récurrence (optionnel)"), {
            "classes": ("collapse",),
            "fields": ("is_recurrent", "recurrence_rule", "end_recurrence"),
            "description": _(
                "Exemples de règle : <b>WEEKLY:SU</b> (tous les dimanches), "
                "<b>WEEKLY:MO,WE,FR</b>, <b>MONTHLY:</b>, <b>YEARLY:</b>."
            ),
        }),
        (_("Stats"), {
            "classes": ("collapse",),
            "fields": ("taux_participation_display",),
        }),
    )

    def taux_participation_display(self, obj):
        # Toujours 2 décimales + symbole
        return f"{obj.taux_participation:.2f} %"

    taux_participation_display.short_description = "Taux de participation"

    def qr_preview(self, obj):
        if obj and obj.qr_code:
            return format_html(
                '<img src="{}" style="height:160px;border-radius:8px;'
                'box-shadow:0 4px 10px rgba(0,0,0,.08);" />',
                obj.qr_code.url
            )
        return _("—")

    qr_preview.short_description = "QR Code"

    def qr_mini(self, obj):
        if obj and obj.qr_code:
            return format_html('<img src="{}" style="height:40px;border-radius:4px;" />', obj.qr_code.url)
        return ""

    qr_mini.short_description = "QR"

    def save_model(self, request, obj, form, change):
        """
        - Génère le QR si absent (ton modèle le fait déjà, mais on assure).
        - Sauvegarde normale.
        """
        if not obj.qr_code:
            obj.generate_and_save_qr_code(obj.code)
        super().save_model(request, obj, form, change)


@admin.register(ParticipationEvenement)
class ParticipationEvenementAdmin(admin.ModelAdmin):
    list_display = ("evenement", "fidele", "qr_code_scanned", "date")
    list_filter = ("qr_code_scanned", ("date", admin.DateFieldListFilter), "evenement__type")
    search_fields = (
        "evenement__titre", "evenement__code", "fidele__user__first_name", "fidele__user__last_name",
        "fidele__phone",
    )
    autocomplete_fields = ("fidele", "evenement")
    readonly_fields = ("date",)

    fieldsets = (
        (None, {
            "fields": ("evenement", "fidele", "qr_code_scanned", "commentaire", "date")
        }),
    )
