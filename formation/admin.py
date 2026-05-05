from django.contrib import admin

from formation.models import (
    Formation, FormationSession, FormationModule,
    FormationInscription, FormationPresence,
)


class FormationModuleInline(admin.TabularInline):
    model = FormationModule
    extra = 0
    fields = ['ordre', 'titre', 'date_seance', 'duree_minutes']


class FormationInscriptionInline(admin.TabularInline):
    model = FormationInscription
    extra = 0
    autocomplete_fields = ['fidele']
    fields = ['fidele', 'statut', 'date_inscription']
    readonly_fields = ['date_inscription']


@admin.register(Formation)
class FormationAdmin(admin.ModelAdmin):
    list_display = ['nom', 'theme', 'duree_mois', 'actif', 'created_at']
    list_filter = ['theme', 'actif']
    search_fields = ['nom', 'description']
    prepopulated_fields = {'slug': ('nom',)}


@admin.register(FormationSession)
class FormationSessionAdmin(admin.ModelAdmin):
    list_display = ['formation', 'nom', 'date_debut', 'date_fin', 'statut', 'taux_remplissage']
    list_filter = ['statut', 'formation__theme']
    search_fields = ['nom', 'formation__nom', 'lieu']
    autocomplete_fields = ['formation', 'formateur']
    date_hierarchy = 'date_debut'
    inlines = [FormationModuleInline, FormationInscriptionInline]


@admin.register(FormationModule)
class FormationModuleAdmin(admin.ModelAdmin):
    list_display = ['session', 'ordre', 'titre', 'date_seance']
    list_filter = ['session__formation__theme']
    search_fields = ['titre']


@admin.register(FormationInscription)
class FormationInscriptionAdmin(admin.ModelAdmin):
    list_display = ['fidele', 'session', 'statut', 'date_inscription', 'taux_presence']
    list_filter = ['statut', 'session__formation__theme']
    search_fields = ['fidele__user__first_name', 'fidele__user__last_name']
    autocomplete_fields = ['fidele', 'session']


@admin.register(FormationPresence)
class FormationPresenceAdmin(admin.ModelAdmin):
    list_display = ['inscription', 'module', 'present', 'created_at']
    list_filter = ['present', 'module__session__formation__theme']
    autocomplete_fields = ['inscription', 'module']
