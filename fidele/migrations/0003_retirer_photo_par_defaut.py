"""Retire l'image par défaut (logo ABMCI) des fidèles : sans photo, le web et l'app affichent les initiales.

- Le champ ``photo`` n'a plus de valeur par défaut (aucune modification de schéma en base).
- Les fidèles pointant sur l'image par défaut, ou sur une copie envoyée comme « photo »
  (même contenu, ex. ``abmci/fideles/7.png``), repassent à « sans photo ». Les vraies photos
  ne sont pas touchées et aucun fichier n'est supprimé du disque.
"""
import hashlib

from django.core.files.storage import default_storage
from django.db import migrations, models

PHOTO_PAR_DEFAUT = "abmci/users/7.png"
# Empreinte du logo par défaut : identifie ses copies téléversées sous un autre nom
LOGO_SHA256 = "c8508669d978d2997f8ed47ee02259682d6974b39d031d3be865ef91d51e9561"
# Nom d'origine « 7.png », éventuellement suffixé par Django (7_AbC1234.png)
COPIES_POSSIBLES = r"(^|/)7(_[A-Za-z0-9]+)?\.png$"


def _empreinte(nom):
    try:
        with default_storage.open(nom, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:  # fichier absent ou illisible : on ne touche pas à la fiche
        return None


def retirer_photo_par_defaut(apps, schema_editor):
    Fidele = apps.get_model("fidele", "Fidele")
    Fidele.objects.filter(photo=PHOTO_PAR_DEFAUT).update(photo=None)
    copies = (Fidele.objects.filter(photo__regex=COPIES_POSSIBLES)
              .values_list("pk", "photo"))
    a_vider = [pk for pk, nom in copies if _empreinte(nom) == LOGO_SHA256]
    if a_vider:
        Fidele.objects.filter(pk__in=a_vider).update(photo=None)


class Migration(migrations.Migration):

    dependencies = [
        ("fidele", "0002_securiser_suppressions_cascade"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fidele",
            name="photo",
            field=models.ImageField(blank=True, null=True, upload_to="abmci/fideles"),
        ),
        migrations.AlterField(  # historique (django-simple-history) : même retrait du défaut
            model_name="historicalfidele",
            name="photo",
            field=models.TextField(blank=True, max_length=100, null=True),
        ),
        # Irréversible côté données : on ne sait plus quelles fiches avaient l'image par défaut
        migrations.RunPython(retirer_photo_par_defaut, migrations.RunPython.noop),
    ]
