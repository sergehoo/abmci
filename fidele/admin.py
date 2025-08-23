from datetime import timedelta

from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.contrib.gis.forms import OSMWidget
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.utils.formats import number_format
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin
from django.contrib.gis import admin as gis_admin
from fidele.models import Department, MembreType, Fidele, Location, TypeLocation, Fonction, OuvrierPermanence, \
    Permanence, Eglise, Familles, SujetPriere, ProblemeParticulier, UserProfileCompletion, PrayerLike, PrayerComment, \
    PrayerRequest, PrayerCategory, BibleVersion, BibleVerse, Banner, DonationCategory, Donation, VerseOfDay, \
    FidelePosition
from django.contrib.gis.db import models

# Register your models here.
admin.site.site_header = 'BACK-END ABMCI'
admin.site.site_title = 'ABMCI Admin Pannel'
admin.site.site_url = 'http://allianceconnect.com/'
admin.site.index_title = 'ABMCI Connect'
admin.empty_value_display = '**Empty**'

admin.site.register(Permanence, SimpleHistoryAdmin)
admin.site.register(OuvrierPermanence, SimpleHistoryAdmin)
admin.site.register(Department, SimpleHistoryAdmin)
admin.site.register(Fonction, SimpleHistoryAdmin)
admin.site.register(MembreType, SimpleHistoryAdmin)
# admin.site.register(Fidele, SimpleHistoryAdmin)
admin.site.register(Location, SimpleHistoryAdmin)
admin.site.register(TypeLocation, SimpleHistoryAdmin)
# admin.site.register(Eglise, SimpleHistoryAdmin)
admin.site.register(Familles, SimpleHistoryAdmin)
admin.site.register(ProblemeParticulier, SimpleHistoryAdmin)
admin.site.register(SujetPriere, SimpleHistoryAdmin)


@admin.register(UserProfileCompletion)
class UserProfileCompletionAdmin(admin.ModelAdmin):
    # Configuration de l'affichage de la liste
    list_display = ('user', 'current_step', 'is_complete', 'last_updated')
    list_filter = ('is_complete', 'current_step')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    ordering = ('-last_updated',)
    date_hierarchy = 'last_updated'

    # Configuration du formulaire d'édition
    fieldsets = (
        (None, {
            'fields': ('user', 'is_complete')
        }),
        ('Progression', {
            'fields': ('current_step', 'last_updated'),
            'classes': ('collapse',)
        }),
    )

    # Champs en lecture seule
    readonly_fields = ('last_updated',)

    # Configuration des actions personnalisées
    actions = ['mark_as_complete', 'reset_completion']

    def mark_as_complete(self, request, queryset):
        queryset.update(is_complete=True, current_step=5)
        self.message_user(request, f"{queryset.count()} profils marqués comme complets")

    mark_as_complete.short_description = "Marquer comme complet"

    def reset_completion(self, request, queryset):
        queryset.update(is_complete=False, current_step=1)
        self.message_user(request, f"{queryset.count()} profils réinitialisés")

    reset_completion.short_description = "Réinitialiser la progression"

    # Amélioration de l'affichage du user
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    # Optionnel: Ajout d'une méthode pour afficher plus d'infos sur l'utilisateur
    def user_info(self, obj):
        return f"{obj.user.get_full_name()} ({obj.user.email})"

    user_info.short_description = "Informations utilisateur"


class CustomOSMWidget(OSMWidget):
    # Paramètres par défaut pour la Côte d'Ivoire (Abidjan)
    default_lon = -3.961808   # Longitude
    default_lat = 5.386192    # Latitude
    default_zoom = 15


@admin.register(Eglise)
class EgliseAdmin(GISModelAdmin):
    list_display = ("name", "ville", "pasteur")
    search_fields = ("name", "ville", "pasteur")
    list_filter = ("ville",)

    # Configuration du widget de carte
    formfield_overrides = {
        models.PointField: {
            "widget": CustomOSMWidget(
                attrs={
                    'map_width': 1000,
                    'map_height': 500,
                    'display_raw': True,
                }
            )
        }
    }


@admin.register(Fidele)
class FideleAdmin(SimpleHistoryAdmin):
    list_display = ("id", "user", "phone", "eglise", "type_membre", "date_entree")
    # IMPORTANT: provide search_fields (used by autocomplete)
    search_fields = ("user__first_name", "user__last_name", "phone", "qlook_id")
    list_filter = ("eglise", "type_membre")

@admin.register(PrayerCategory)
class PrayerCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name',)
    # prepopulated_fields = {'slug': ('name',)}  # Si vous ajoutez un champ slug
    ordering = ('name',)
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related()


@admin.register(PrayerRequest)
class PrayerRequestAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'user',
        'get_prayer_type_display',
        'category',
        'is_anonymous',
        'created_at',
        'comments_count',
        'likes_count',
        # 'audio_player'
    )
    list_filter = ('prayer_type', 'is_anonymous', 'category', 'created_at')
    search_fields = ('title', 'content', 'user__username')
    raw_id_fields = ('user', 'category')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at', 'comments_count', 'likes_count')
    fieldsets = (
        (None, {
            'fields': ('user', 'title', 'content', 'prayer_type', 'category')
        }),
        ('Média', {
            'fields': ['audio_note'],
            'classes': ('collapse',)
        }),
        ('Options', {
            'fields': ('is_anonymous',),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Statistiques', {
            'fields': ('comments_count', 'likes_count'),
            'classes': ('collapse',)
        }),
    )

    def comments_count(self, obj):
        return obj.comments.count()
    comments_count.short_description = 'Commentaires'

    def likes_count(self, obj):
        return obj.likes.count()
    likes_count.short_description = 'Likes'

    def audio_player(self, obj):
        if obj.audio_note:
            return format_html(
                '<audio controls src="{}" style="width: 100%"></audio>',
                obj.audio_note.url
            )
        return "-"
    audio_player.short_description = 'Audio'

    def get_queryset(self, request):
        return super().get_queryset(request)\
            .select_related('user', 'category')\
            .prefetch_related('comments', 'likes')


@admin.register(PrayerComment)
class PrayerCommentAdmin(admin.ModelAdmin):
    list_display = ('content', 'user', 'prayer', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('content', 'user__username', 'prayer__title')
    raw_id_fields = ('user', 'prayer')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request)\
            .select_related('user', 'prayer')


@admin.register(PrayerLike)
class PrayerLikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'prayer', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'prayer__title')
    raw_id_fields = ('user', 'prayer')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request)\
            .select_related('user', 'prayer')

@admin.register(BibleVersion)
class BibleVersionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'language', 'total_verses', 'updated_at')
    list_filter = ('language',)
    search_fields = ('code', 'name')
    ordering = ('code',)

@admin.register(BibleVerse)
class BibleVerseAdmin(admin.ModelAdmin):
    list_display = ('version', 'book', 'chapter', 'verse', 'updated_at')
    list_filter = ('version', 'book')
    search_fields = ('book', 'text')
    list_select_related = ('version',)
    ordering = ('version', 'book', 'chapter', 'verse')

@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "active", "order", "updated_at")
    list_filter = ("active",)
    search_fields = ("title", "subtitle")
    ordering = ("order", "-updated_at")


@admin.register(DonationCategory)
class DonationCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'donation_count')
    search_fields = ('code', 'name')
    ordering = ('code',)

    def donation_count(self, obj):
        return obj.donation_set.count()

    donation_count.short_description = "Nombre de dons"


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "formatted_amount",
        "category_link",
        "user_link",
        "payment_method",
        "status_badge",
        "recurrence",
        "created_at",
        "paid_at",
        "authorization_link",
    )
    list_display_links = ("reference",)
    list_filter = (
        "status",
        "payment_method",
        "recurrence",
        "category",
        ("paid_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "reference",
        "user__email",
        "user__first_name",
        "user__last_name",
        "category__name",
    )
    list_select_related = ("user", "category")
    actions = ("resend_payment_link", "mark_as_successful", "mark_as_failed")
    readonly_fields = ("reference", "created_at", "authorization_url")
    autocomplete_fields = ("user", "category")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50

    fieldsets = (
        (None, {"fields": ("user", "anonymous", "category", "amount")}),
        ("Paiement", {"fields": ("payment_method", "reference", "status", "authorization_url")}),
        ("Récurrence", {"fields": ("recurrence",)}),
        ("Dates", {"fields": ("created_at", "paid_at")}),
    )

    # ---------- Helpers d’affichage ----------

    @admin.display(description="Montant", ordering="amount")
    def formatted_amount(self, obj: Donation) -> str:
        # number_format gère les séparateurs en respectant LANGUAGE_CODE
        return f"{number_format(obj.amount, force_grouping=True)} XOF"

    @admin.display(description="Catégorie", ordering="category__name")
    def category_link(self, obj: Donation) -> str:
        if not obj.category_id:
            return "-"
        try:
            url = reverse("admin:%s_%s_change" % (obj.category._meta.app_label, obj.category._meta.model_name),
                          args=[obj.category.pk])
        except NoReverseMatch:
            return obj.category.name
        return format_html('<a href="{}">{}</a>', url, obj.category.name)

    @admin.display(description="Donateur", ordering="user__last_name")
    def user_link(self, obj: Donation) -> str:
        if not obj.user:
            return "Anonyme" if obj.anonymous else "Invité"
        label = obj.user.get_full_name() or obj.user.email or f"Utilisateur #{obj.user_id}"
        try:
            url = reverse("admin:%s_%s_change" % (obj.user._meta.app_label, obj.user._meta.model_name),
                          args=[obj.user.pk])
        except NoReverseMatch:
            return label
        return format_html('<a href="{}">{}</a>', url, label)

    @admin.display(description="Statut")
    def status_badge(self, obj: Donation) -> str:
        colors = {
            "pending": "#f59e0b",    # orange-500
            "success": "#10b981",    # emerald-500
            "failed": "#ef4444",     # red-500
            "abandoned": "#6b7280",  # gray-500
        }
        color = colors.get(obj.status, "#3b82f6")  # blue-500 par défaut
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;border-radius:10px;font-weight:600">'
            "{}</span>",
            color,
            obj.status.upper(),
        )

    @admin.display(description="Lien Paiement")
    def authorization_link(self, obj: Donation) -> str:
        if not obj.authorization_url:
            return "-"
        return format_html('<a href="{}" target="_blank" rel="noopener">Ouvrir</a>', obj.authorization_url)

    # ---------- Actions ----------

    @admin.action(description="Renvoyer le lien de paiement")
    def resend_payment_link(self, request, queryset):
        # Exemple minimal : ici on se contente de compter les liens valides.
        # Tu peux brancher un envoi email/SMS selon ton infra.
        count = 0
        for d in queryset:
            if d.authorization_url:
                count += 1
                # TODO: implémenter l’envoi (email/SMS) avec d.authorization_url
        if count:
            self.message_user(request, f"{count} lien(s) de paiement renvoyé(s).", level=messages.SUCCESS)
        else:
            self.message_user(request, "Aucun lien de paiement disponible à renvoyer.", level=messages.WARNING)

    @admin.action(description="Marquer comme payé (success)")
    def mark_as_successful(self, request, queryset):
        # On ne touche qu’aux pending/failed/abandoned pour éviter d’écraser du 'success'
        updatable = queryset.exclude(status="success")
        updated = updatable.update(status="success", paid_at=timezone.now())
        self.message_user(request, f"{updated} don(s) marqué(s) comme payé(s).", level=messages.SUCCESS)

    @admin.action(description="Marquer comme échoué (failed)")
    def mark_as_failed(self, request, queryset):
        updatable = queryset.exclude(status="failed")
        updated = updatable.update(status="failed")
        self.message_user(request, f"{updated} don(s) marqué(s) comme échoué(s).", level=messages.WARNING)

    # ---------- Optimisations ----------

    def get_queryset(self, request):
        # on garde select_related + possibilité d’annotations futures
        qs = super().get_queryset(request).select_related("user", "category")
        return qs

@admin.register(VerseOfDay)
class VerseOfDayAdmin(admin.ModelAdmin):
    # Configuration de l'affichage dans la liste
    list_display = ('date', 'eglise', 'reference', 'version', 'language', 'context_key', 'created_at')
    list_filter = ('eglise', 'version', 'language', 'context_key', 'date')
    search_fields = ('reference', 'text', 'context_key', 'eglise__nom')
    ordering = ('-date', 'eglise')
    date_hierarchy = 'date'

    # Configuration du formulaire d'édition
    fieldsets = (
        (None, {
            'fields': ('date', 'eglise', 'version', 'language', 'context_key')
        }),
        ('Contenu du verset', {
            'fields': ('reference', 'text')
        }),
        ('Métadonnées', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )

    # Champs en lecture seule
    readonly_fields = ('created_at',)

    # Actions personnalisées
    actions = ['duplicate_verse']

    def duplicate_verse(self, request, queryset):
        for verse in queryset:
            verse.pk = None
            verse.date = verse.date + timedelta(days=1)
            verse.save()
        self.message_user(request, f"{queryset.count()} verset(s) dupliqué(s) avec succès.")

    duplicate_verse.short_description = "Dupliquer les versets sélectionnés (date +1 jour)"


@admin.register(FidelePosition)
class FidelePositionAdmin(admin.ModelAdmin):
    # ... configuration existante ...

    actions = ['export_positions_csv']

    def export_positions_csv(self, request, queryset):
        """Action pour exporter les positions sélectionnées en CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="positions.csv"'

        writer = csv.writer(response)
        writer.writerow(['Fidèle', 'Latitude', 'Longitude', 'Précision', 'Date', 'Source'])

        for position in queryset:
            writer.writerow([
                str(position.fidele),
                position.latitude,
                position.longitude,
                position.accuracy or '',
                position.captured_at,
                position.source
            ])

        return response

    export_positions_csv.short_description = "Exporter les positions sélectionnées en CSV"