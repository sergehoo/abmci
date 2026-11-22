# Fusion des deux migrations 0002 créées en parallèle (conflit qui bloquait `migrate`).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('formation', '0002_auto_populate_slug'),
        ('formation', '0002_rename_format__formation_format_and_more'),
    ]

    operations = []
