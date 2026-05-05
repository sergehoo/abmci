"""Génère un slug pour toutes les Formation existantes qui n'en ont pas."""
from django.db import migrations
from django.utils.text import slugify


def populate_slugs(apps, schema_editor):
    Formation = apps.get_model('formation', 'Formation')
    used = set(Formation.objects.exclude(slug__isnull=True)
                                .exclude(slug='')
                                .values_list('slug', flat=True))
    for f in Formation.objects.filter(slug__in=['', None]) | Formation.objects.filter(slug__isnull=True):
        base = slugify(f.nom or 'formation') or f"formation-{f.pk}"
        slug = base
        n = 2
        while slug in used:
            slug = f"{base}-{n}"
            n += 1
        used.add(slug)
        f.slug = slug
        f.save(update_fields=['slug'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('formation', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(populate_slugs, noop),
    ]
