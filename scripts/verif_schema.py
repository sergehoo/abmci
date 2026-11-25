"""
Vérification en lecture seule : les modèles Django (fidele, event, eden) correspondent-ils au schéma réel ?
Usage : python manage.py shell < scripts/verif_schema.py
Utile quand l'historique des migrations du serveur diffère de celui du dépôt (migrations régénérées) :
Django se fie aux noms des migrations, ce script vérifie les tables et colonnes effectivement présentes.
"""
from django.apps import apps
from django.db import connection

ecarts = []
with connection.cursor() as cursor:
    tables = set(connection.introspection.table_names(cursor))
    for app_label in ("fidele", "event", "eden"):
        for model in apps.get_app_config(app_label).get_models():
            if not model._meta.managed or model._meta.proxy:
                continue
            table = model._meta.db_table
            if table not in tables:
                ecarts.append(f"table manquante : {table}")
                continue
            colonnes = {c.name for c in connection.introspection.get_table_description(cursor, table)}
            for field in model._meta.local_fields:
                if field.column and field.column not in colonnes:
                    ecarts.append(f"colonne manquante : {table}.{field.column}")
            for field in model._meta.local_many_to_many:
                through = field.remote_field.through
                if through._meta.auto_created and through._meta.db_table not in tables:
                    ecarts.append(f"table manquante : {through._meta.db_table}")

print("SCHEMA_OK" if not ecarts else "SCHEMA_ECARTS\n" + "\n".join(ecarts))
