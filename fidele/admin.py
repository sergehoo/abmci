from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.utils.formats import number_format
from django.utils.html import format_html

from abmci.services.notifications import User
from fidele.models import (
    Department,
    MembreType,
    Fidele,
    Location,
    TypeLocation,
    Fonction,
    OuvrierPermanence,
    Permanence,
    Eglise,
    Familles,
    SujetPriere,
    ProblemeParticulier,
    UserProfileCompletion,
    PrayerLike,
    PrayerComment,
    PrayerRequest,
    PrayerCategory,
    BibleVersion,
    BibleVerse,
    Banner,
    DonationCategory,
    Donation,
    VerseOfDay,
    FidelePosition,
    ProblemCategory,
    ProblemReport,
    Role,
    Device,
    ProblemAction,
    EntretienPastoral,
    NotePastorale,
    Conseil,
    DemandePriere,
    TransferHistory,
    Notification,
    Competence,
    Service,
    ParticipationService,
    Anniversaire,
    Sacrement,
    Deces,
    PrayerAttachment,
    BibleTag,
    VerseUsage,
    AccountDeletionRequest, NotificationUser,
)

# Configuration globale de l’admin
admin.site.site_header = "BACK-END ABMCI"
admin.site.site_title = "ABMCI Admin Pannel"
admin.site.site_url = "http://allianceconnect.com/"
admin.site.index_title = "ABMCI Connect"
admin.empty_value_display = "**Empty**"


# ---------------------------------------------------------------------------
# PROFIL UTILISATEUR / COMPLETION
# ---------------------------------------------------------------------------

@admin.register(UserProfileCompletion)
class UserProfileCompletionAdmin(admin.ModelAdmin):
    list_display = ("user", "current_step", "is_complete", "last_updated")
    list_filter = ("is_complete", "current_step")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    ordering = ("-last_updated",)
    date_hierarchy = "last_updated"

    fieldsets = (
        (
            None,
            {
                "fields": ("user", "is_complete"),
            },
        ),
        (
            "Progression",
            {
                "fields": ("current_step", "last_updated"),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = ("last_updated",)

    actions = ["mark_as_complete", "reset_completion"]

    def mark_as_complete(self, request, queryset):
        queryset.update(is_complete=True, current_step=5)
        self.message_user(
            request, f"{queryset.count()} profils marqués comme complets"
        )

    mark_as_complete.short_description = "Marquer comme complet"

    def reset_completion(self, request, queryset):
        queryset.update(is_complete=False, current_step=1)
        self.message_user(
            request, f"{queryset.count()} profils réinitialisés"
        )

    reset_completion.short_description = "Réinitialiser la progression"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    def user_info(self, obj):
        return f"{obj.user.get_full_name()} ({obj.user.email})"

    user_info.short_description = "Informations utilisateur"


# ---------------------------------------------------------------------------
# PRIERES (feed, likes, commentaires)
# ---------------------------------------------------------------------------

@admin.register(PrayerCategory)
class PrayerCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "icon", "created_at")
    list_filter = ("created_at",)
    search_fields = ("name",)
    ordering = ("name",)
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related()


@admin.register(PrayerRequest)
class PrayerRequestAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "user",
        "get_prayer_type_display",
        "category",
        "is_anonymous",
        "created_at",
        "comments_count",
        "likes_count",
    )
    list_filter = ("prayer_type", "is_anonymous", "category", "created_at")
    search_fields = ("title", "content", "user__username")
    raw_id_fields = ("user", "category")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at", "comments_count", "likes_count")
    fieldsets = (
        (
            None,
            {
                "fields": ("user", "title", "content", "prayer_type", "category"),
            },
        ),
        (
            "Média",
            {
                "fields": ["audio_note"],
                "classes": ("collapse",),
            },
        ),
        (
            "Options",
            {
                "fields": ("is_anonymous",),
                "classes": ("collapse",),
            },
        ),
        (
            "Dates",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
        (
            "Statistiques",
            {
                "fields": ("comments_count", "likes_count"),
                "classes": ("collapse",),
            },
        ),
    )

    def comments_count(self, obj):
        return obj.comments.count()

    comments_count.short_description = "Commentaires"

    def likes_count(self, obj):
        return obj.likes.count()

    likes_count.short_description = "Likes"

    def audio_player(self, obj):
        if obj.audio_note:
            return format_html(
                '<audio controls src="{}" style="width: 100%"></audio>',
                obj.audio_note.url,
            )
        return "-"

    audio_player.short_description = "Audio"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user", "category")
            .prefetch_related("comments", "likes")
        )


@admin.register(PrayerComment)
class PrayerCommentAdmin(admin.ModelAdmin):
    list_display = ("content", "user", "prayer", "created_at")
    list_filter = ("created_at",)
    search_fields = ("content", "user__username", "prayer__title")
    raw_id_fields = ("user", "prayer")
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "prayer")


@admin.register(PrayerLike)
class PrayerLikeAdmin(admin.ModelAdmin):
    list_display = ("user", "prayer", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "prayer__title")
    raw_id_fields = ("user", "prayer")
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "prayer")


@admin.register(PrayerAttachment)
class PrayerAttachmentAdmin(admin.ModelAdmin):
    list_display = ("prayer", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("prayer__title",)


# ---------------------------------------------------------------------------
# BIBLE (versions, versets, tags, usage, verset du jour)
# ---------------------------------------------------------------------------

@admin.register(BibleVersion)
class BibleVersionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "language", "total_verses", "updated_at")
    list_filter = ("language",)
    search_fields = ("code", "name")
    ordering = ("code",)


@admin.register(BibleVerse)
class BibleVerseAdmin(admin.ModelAdmin):
    list_display = ("version", "book", "chapter", "verse", "updated_at")
    list_filter = ("version", "book")
    search_fields = ("book", "text")
    list_select_related = ("version",)
    ordering = ("version", "book", "chapter", "verse")


@admin.register(BibleTag)
class BibleTagAdmin(admin.ModelAdmin):
    list_display = ("sender", "recipient", "book", "chapter", "verse", "created_at")
    search_fields = ("sender__username", "recipient__username", "book")


@admin.register(VerseOfDay)
class VerseOfDayAdmin(admin.ModelAdmin):
    list_display = ("date", "eglise", "reference", "version", "language", "context_key", "created_at")
    list_filter = ("date", "eglise", "version", "language", "context_key")
    search_fields = ("reference",)


@admin.register(VerseUsage)
class VerseUsageAdmin(admin.ModelAdmin):
    list_display = ("eglise", "used_on", "book", "chapter", "verse")
    list_filter = ("used_on", "eglise")


# ---------------------------------------------------------------------------
# BANNIÈRES (annonces)
# ---------------------------------------------------------------------------

@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "active", "order", "updated_at")
    list_filter = ("active",)
    search_fields = ("title", "subtitle")
    ordering = ("order", "-updated_at")


# ---------------------------------------------------------------------------
# DONS
# ---------------------------------------------------------------------------

@admin.register(DonationCategory)
class DonationCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "donation_count")
    search_fields = ("code", "name")
    ordering = ("code",)

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
        (
            "Paiement",
            {"fields": ("payment_method", "reference", "status", "authorization_url")},
        ),
        ("Récurrence", {"fields": ("recurrence",)}),
        ("Dates", {"fields": ("created_at", "paid_at")}),
    )

    # ---------- Helpers d’affichage ----------

    @admin.display(description="Montant", ordering="amount")
    def formatted_amount(self, obj: Donation) -> str:
        return f"{number_format(obj.amount, force_grouping=True)} XOF"

    @admin.display(description="Catégorie", ordering="category__name")
    def category_link(self, obj: Donation) -> str:
        if not obj.category_id:
            return "-"
        try:
            url = reverse(
                f"admin:{obj.category._meta.app_label}_{obj.category._meta.model_name}_change",
                args=[obj.category.pk],
            )
        except NoReverseMatch:
            return obj.category.name
        return format_html('<a href="{}">{}</a>', url, obj.category.name)

    @admin.display(description="Donateur", ordering="user__last_name")
    def user_link(self, obj: Donation) -> str:
        if not obj.user:
            return "Anonyme" if obj.anonymous else "Invité"
        label = obj.user.get_full_name() or obj.user.email or f"Utilisateur #{obj.user_id}"
        try:
            url = reverse(
                f"admin:{obj.user._meta.app_label}_{obj.user._meta.model_name}_change",
                args=[obj.user.pk],
            )
        except NoReverseMatch:
            return label
        return format_html('<a href="{}">{}</a>', url, label)

    @admin.display(description="Statut")
    def status_badge(self, obj: Donation) -> str:
        colors = {
            "pending": "#f59e0b",
            "success": "#10b981",
            "failed": "#ef4444",
            "abandoned": "#6b7280",
        }
        color = colors.get(obj.status, "#3b82f6")
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;'
            'border-radius:10px;font-weight:600">{}</span>',
            color,
            obj.status.upper(),
        )

    @admin.display(description="Lien Paiement")
    def authorization_link(self, obj: Donation) -> str:
        if not obj.authorization_url:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Ouvrir</a>',
            obj.authorization_url,
        )

    # ---------- Actions ----------

    @admin.action(description="Renvoyer le lien de paiement")
    def resend_payment_link(self, request, queryset):
        count = 0
        for d in queryset:
            if d.authorization_url:
                count += 1
                # TODO: implémenter l’envoi (email/SMS) avec d.authorization_url
        if count:
            self.message_user(
                request, f"{count} lien(s) de paiement renvoyé(s).", level=messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "Aucun lien de paiement disponible à renvoyer.",
                level=messages.WARNING,
            )

    @admin.action(description="Marquer comme payé (success)")
    def mark_as_successful(self, request, queryset):
        updatable = queryset.exclude(status="success")
        updated = updatable.update(status="success", paid_at=timezone.now())
        self.message_user(
            request, f"{updated} don(s) marqué(s) comme payé(s).", level=messages.SUCCESS
        )

    @admin.action(description="Marquer comme échoué (failed)")
    def mark_as_failed(self, request, queryset):
        updatable = queryset.exclude(status="failed")
        updated = updatable.update(status="failed")
        self.message_user(
            request, f"{updated} don(s) marqué(s) comme échoué(s).", level=messages.WARNING
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "category")


# ---------------------------------------------------------------------------
# LOCALISATION / POSITIONS
# ---------------------------------------------------------------------------

@admin.register(FidelePosition)
class FidelePositionAdmin(admin.ModelAdmin):
    list_display = ["fidele", "latitude", "longitude", "captured_at", "source"]
    list_filter = ["source", "captured_at"]
    search_fields = ["fidele__user__username"]
    actions = ["export_positions_csv"]

    def export_positions_csv(self, request, queryset):
        """Action pour exporter les positions sélectionnées en CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="positions.csv"'

        writer = csv.writer(response)
        writer.writerow(
            ["Fidèle", "Latitude", "Longitude", "Précision", "Date", "Source"]
        )

        for position in queryset:
            writer.writerow(
                [
                    str(position.fidele),
                    position.latitude,
                    position.longitude,
                    position.accuracy or "",
                    position.captured_at,
                    position.source,
                ]
            )

        return response

    export_positions_csv.short_description = (
        "Exporter les positions sélectionnées en CSV"
    )


# ---------------------------------------------------------------------------
# PROBLEMS / SUPPORT
# ---------------------------------------------------------------------------

@admin.register(ProblemCategory)
class ProblemCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(ProblemReport)
class ProblemReportAdmin(admin.ModelAdmin):
    list_display = ["title", "eglise", "reporter", "assignee", "status", "severity", "created_at"]
    list_filter = ["status", "severity", "created_at", "eglise"]
    search_fields = ["title", "description", "reporter__user__username"]
    raw_id_fields = ["reporter", "assignee"]


@admin.register(ProblemAction)
class ProblemActionAdmin(admin.ModelAdmin):
    list_display = ["problem", "author", "type", "created_at"]
    list_filter = ["type", "created_at"]
    search_fields = ["problem__title", "author__user__username"]


@admin.register(ProblemeParticulier)
class ProblemeParticulierAdmin(admin.ModelAdmin):
    list_display = ["fidele", "type_probleme", "gravite", "statut", "date_decouverte"]
    list_filter = ["gravite", "statut", "date_decouverte"]
    search_fields = ["fidele__user__username", "type_probleme"]


# ---------------------------------------------------------------------------
# SUJETS / FAMILLES / ROLES / EGLISE / LOCATIONS
# ---------------------------------------------------------------------------

@admin.register(SujetPriere)
class SujetPriereAdmin(admin.ModelAdmin):
    list_display = ["titre", "fidele", "date", "traitement"]
    list_filter = ["traitement", "date"]
    search_fields = ["titre", "fidele__user__username"]


@admin.register(Familles)
class FamillesAdmin(admin.ModelAdmin):
    list_display = ["name", "mission"]
    search_fields = ["name", "mission__name"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]
    search_fields = ["code", "name"]


@admin.register(MembreType)
class MembreTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "duree"]
    search_fields = ["name"]


@admin.register(TypeLocation)
class TypeLocationAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "parent"]
    list_filter = ["type"]
    search_fields = ["name"]


@admin.register(Eglise)
class EgliseAdmin(admin.ModelAdmin):
    list_display = ["name", "ville", "pasteur", "verse_date"]
    search_fields = ["name", "ville", "pasteur"]
    list_filter = ["ville"]


# ---------------------------------------------------------------------------
# FIDELES / USER
# ---------------------------------------------------------------------------

class FideleInline(admin.StackedInline):
    model = Fidele
    can_delete = False
    verbose_name_plural = "Profil Fidèle"
    fk_name = "user"


class CustomUserAdmin(UserAdmin):
    inlines = [FideleInline]
    list_display = ["username", "email", "first_name", "last_name", "is_staff", "get_eglise"]

    def get_eglise(self, obj):
        if hasattr(obj, "fidele"):
            return obj.fidele.eglise
        return None

    get_eglise.short_description = "Église"

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        return super().get_inline_instances(request, obj)


@admin.register(Fidele)
class FideleAdmin(admin.ModelAdmin):
    list_display = ["user", "qlook_id", "eglise", "departement", "fonction", "sexe", "created_at"]
    list_filter = ["eglise", "departement", "fonction", "sexe", "situation_matrimoniale", "created_at"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "qlook_id"]
    raw_id_fields = ["user", "marie_a", "pere", "mere"]
    filter_horizontal = ["frere", "soeur", "roles"]


# ---------------------------------------------------------------------------
# PASTORAL / CONSEILS / DEMANDES / TRANSFERTS
# ---------------------------------------------------------------------------

@admin.register(EntretienPastoral)
class EntretienPastoralAdmin(admin.ModelAdmin):
    list_display = ["fidele", "type_entretien", "date", "pasteur", "confidential"]
    list_filter = ["type_entretien", "date", "confidential"]
    search_fields = ["fidele__user__username", "pasteur__username"]


@admin.register(NotePastorale)
class NotePastoraleAdmin(admin.ModelAdmin):
    list_display = ["fidele", "auteur", "titre", "date", "confidentialite"]
    list_filter = ["confidentialite", "date"]
    search_fields = ["fidele__user__username", "auteur__username", "titre"]


@admin.register(Conseil)
class ConseilAdmin(admin.ModelAdmin):
    list_display = ["sujet", "type_conseil", "date_conseil", "confidential"]
    list_filter = ["type_conseil", "date_conseil", "confidential"]
    search_fields = ["sujet"]
    filter_horizontal = ["conseillers", "participants"]


@admin.register(DemandePriere)
class DemandePriereAdmin(admin.ModelAdmin):
    list_display = ["demandeur", "sujet", "statut", "date_demande", "publique"]
    list_filter = ["statut", "date_demande", "publique"]
    search_fields = ["demandeur__user__username", "sujet"]
    filter_horizontal = ["equipe_priere"]


@admin.register(TransferHistory)
class TransferHistoryAdmin(admin.ModelAdmin):
    list_display = ["fidele", "ancienne_eglise", "nouvelle_eglise", "date_transfert"]
    list_filter = ["date_transfert"]
    search_fields = ["fidele__user__username"]


# ---------------------------------------------------------------------------
# NOTIFICATIONS / DEVICES
# ---------------------------------------------------------------------------

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [ "type", "title", "created_at"]
    list_filter = ["type",  "created_at"]
    search_fields = ["title"]


@admin.register(NotificationUser)
class NotificationUserAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification', 'is_read', 'created_at', 'read_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['user__username', 'notification__title']
    raw_id_fields = ['user', 'notification']
    readonly_fields = ['created_at']

    def mark_as_read(self, request, queryset):
        updated = queryset.filter(is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )
        self.message_user(request, f"{updated} notifications marquées comme lues.")

    def mark_as_unread(self, request, queryset):
        updated = queryset.filter(is_read=True).update(
            is_read=False,
            read_at=None
        )
        self.message_user(request, f"{updated} notifications marquées comme non lues.")

    mark_as_read.short_description = "Marquer comme lu"
    mark_as_unread.short_description = "Marquer comme non lu"

    actions = [mark_as_read, mark_as_unread]
@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "platform", "last_seen", "created_at"]
    list_filter = ["platform", "created_at"]
    search_fields = ["user__username", "token"]


# ---------------------------------------------------------------------------
# COMPETENCES / SERVICES / PARTICIPATIONS / EVENEMENTS
# ---------------------------------------------------------------------------

@admin.register(Competence)
class CompetenceAdmin(admin.ModelAdmin):
    list_display = ["nom", "categorie"]
    list_filter = ["categorie"]
    search_fields = ["nom"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["nom", "date", "responsable"]
    list_filter = ["date"]
    search_fields = ["nom", "responsable__user__username"]


@admin.register(ParticipationService)
class ParticipationServiceAdmin(admin.ModelAdmin):
    list_display = ["fidele", "service", "role", "presence"]
    list_filter = ["role", "presence"]
    search_fields = ["fidele__user__username", "service__nom"]


@admin.register(Anniversaire)
class AnniversaireAdmin(admin.ModelAdmin):
    list_display = ["fidele", "date_anniversaire", "type_anniversaire", "celebration_organisee"]
    list_filter = ["type_anniversaire", "celebration_organisee"]
    search_fields = ["fidele__user__username"]


@admin.register(Sacrement)
class SacrementAdmin(admin.ModelAdmin):
    list_display = ["fidele", "type_sacrement", "date", "officiant", "lieu"]
    list_filter = ["type_sacrement", "date"]
    search_fields = ["fidele__user__username", "officiant__username"]


@admin.register(Deces)
class DecesAdmin(admin.ModelAdmin):
    list_display = ["defunt", "date_deces", "lieu_deces", "date_ceremonie"]
    search_fields = ["defunt__user__username"]


# ---------------------------------------------------------------------------
# DEMANDE DE SUPPRESSION DE COMPTE
# ---------------------------------------------------------------------------

@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ["user", "status", "requested_at", "processed_at"]
    list_filter = ["status", "requested_at"]
    search_fields = ["user__username"]


# ---------------------------------------------------------------------------
# USER CUSTOM ADMIN
# ---------------------------------------------------------------------------

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)