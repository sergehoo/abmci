from django.contrib import admin

from eden.models import Fiancailles, Mariage


# Register your models here.
@admin.register(Fiancailles)
class FiancaillesAdmin(admin.ModelAdmin):
    list_display = ("homme", "femme", "date_demande", "date_ceremonie", "statut")
    list_filter = ("statut", "date_ceremonie")
    search_fields = (
        "homme__user__first_name", "homme__user__last_name", "femme__user__first_name", "femme__user__last_name")


@admin.register(Mariage)
class MariageAdmin(admin.ModelAdmin):
    list_display = ("date_mariage", "lieu_mariage", "officiant", "numero_acte")
    list_filter = ("date_mariage",)
    search_fields = ("numero_acte", "lieu_mariage", "officiant__username")
    filter_horizontal = ("couple", "temoins")
