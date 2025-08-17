from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.contrib.gis.forms import OSMWidget
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin
from django.contrib.gis import admin as gis_admin
from fidele.models import Department, MembreType, Fidele, Location, TypeLocation, Fonction, OuvrierPermanence, \
    Permanence, Eglise, Familles, SujetPriere, ProblemeParticulier, UserProfileCompletion, PrayerLike, PrayerComment, \
    PrayerRequest, PrayerCategory, BibleVersion, BibleVerse, Banner, DonationCategory, Donation
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
        'reference',
        'formatted_amount',
        'category_link',
        'user_link',
        'payment_method',
        'status_badge',
        'recurrence',
        'created_at',
        'paid_at',
        'authorization_link'
    )
    list_filter = (
        'status',
        'payment_method',
        'recurrence',
        'category',
        ('paid_at', admin.DateFieldListFilter),
    )
    search_fields = ('reference', 'user__email', 'user__first_name', 'user__last_name')
    list_select_related = ('user', 'category')
    actions = ['resend_payment_link', 'mark_as_successful']
    readonly_fields = ('reference', 'created_at', 'authorization_url')
    fieldsets = (
        (None, {
            'fields': ('user', 'anonymous', 'category', 'amount')
        }),
        ('Paiement', {
            'fields': ('payment_method', 'reference', 'status', 'authorization_url')
        }),
        ('Récurrence', {
            'fields': ('recurrence',)
        }),
        ('Dates', {
            'fields': ('created_at', 'paid_at')
        }),
    )

    def formatted_amount(self, obj):
        return f"{obj.amount:,} XOF"

    formatted_amount.short_description = "Montant"
    formatted_amount.admin_order_field = 'amount'

    def category_link(self, obj):
        url = reverse("admin:donations_donationcategory_change", args=[obj.category.id])
        return format_html('<a href="{}">{}</a>', url, obj.category.name)

    category_link.short_description = "Catégorie"
    category_link.admin_order_field = 'category'

    def user_link(self, obj):
        if not obj.user:
            return "Anonyme" if obj.anonymous else "Invité"
        url = reverse("admin:accounts_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.email)

    user_link.short_description = "Donateur"
    user_link.admin_order_field = 'user'

    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'success': 'green',
            'failed': 'red',
            'abandoned': 'gray'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 10px">{}</span>',
            colors.get(obj.status, 'blue'),
            obj.status.upper()
        )

    status_badge.short_description = "Statut"

    def authorization_link(self, obj):
        if not obj.authorization_url:
            return "-"
        return format_html('<a href="{}" target="_blank">Lien de paiement</a>', obj.authorization_url)

    authorization_link.short_description = "Lien Paiement"

    @admin.action(description="Renvoyer le lien de paiement")
    def resend_payment_link(self, request, queryset):
        # Implémentez la logique d'envoi ici
        self.message_user(request, f"{queryset.count()} liens envoyés")

    @admin.action(description="Marquer comme payé")
    def mark_as_successful(self, request, queryset):
        updated = queryset.filter(status='pending').update(status='success', paid_at=timezone.now())
        self.message_user(request, f"{updated} dons marqués comme payés")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'category')