from django.apps import AppConfig


class FideleConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fidele'

    def ready(self):
        import fidele.signals
        import abmci.receivers
