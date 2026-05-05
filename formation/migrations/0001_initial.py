"""
Migration initiale du module formation.

Crée :
- Formation
- FormationSession
- FormationModule
- FormationInscription
- FormationPresence
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('fidele', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Formation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('nom', models.CharField(max_length=140)),
                ('theme', models.CharField(choices=[
                    ('pastorale', 'Formation pastorale'),
                    ('bapteme',   'Préparation au baptême'),
                    ('mariage',   'Préparation au mariage'),
                    ('disciple',  'Discipulat'),
                    ('autre',     'Autre'),
                ], default='autre', max_length=20)),
                ('description', models.TextField(blank=True)),
                ('duree_mois', models.PositiveSmallIntegerField(default=3)),
                ('format', models.CharField(blank=True, help_text='ex: Présentiel, En couple, Groupe de 8-12…', max_length=120)),
                ('actif', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('formateur_principal', models.ForeignKey(blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='formations_principales',
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'Formation',
                     'verbose_name_plural': 'Formations',
                     'ordering': ['theme', 'nom']},
        ),
        migrations.CreateModel(
            name='FormationSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nom', models.CharField(help_text='ex: « Promo Septembre 2026 »', max_length=140)),
                ('date_debut', models.DateField()),
                ('date_fin', models.DateField(blank=True, null=True)),
                ('lieu', models.CharField(blank=True, max_length=200)),
                ('capacite_max', models.PositiveSmallIntegerField(default=20)),
                ('statut', models.CharField(choices=[
                    ('planifiee', 'Planifiée'),
                    ('en_cours',  'En cours'),
                    ('terminee',  'Terminée'),
                    ('annulee',   'Annulée'),
                ], default='planifiee', max_length=12)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('formation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='sessions', to='formation.formation')),
                ('formateur', models.ForeignKey(blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sessions_animees',
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'Session de formation',
                     'verbose_name_plural': 'Sessions de formation',
                     'ordering': ['-date_debut']},
        ),
        migrations.AddIndex(
            model_name='formationsession',
            index=models.Index(fields=['formation', '-date_debut'],
                               name='formation_f_formati_4b2f6e_idx'),
        ),
        migrations.CreateModel(
            name='FormationModule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ordre', models.PositiveSmallIntegerField(default=1)),
                ('titre', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('date_seance', models.DateTimeField(blank=True, null=True)),
                ('duree_minutes', models.PositiveSmallIntegerField(default=90)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='modules', to='formation.formationsession')),
            ],
            options={'verbose_name': 'Module de formation',
                     'verbose_name_plural': 'Modules de formation',
                     'ordering': ['session', 'ordre']},
        ),
        migrations.AddIndex(
            model_name='formationmodule',
            index=models.Index(fields=['session', 'ordre'],
                               name='formation_f_session_8c1d3a_idx'),
        ),
        migrations.CreateModel(
            name='FormationInscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_inscription', models.DateTimeField(auto_now_add=True)),
                ('statut', models.CharField(choices=[
                    ('actif',     'Actif'),
                    ('abandonne', 'Abandonné'),
                    ('diplome',   'Diplômé'),
                    ('echec',     'Non validé'),
                ], default='actif', max_length=12)),
                ('note_finale', models.PositiveSmallIntegerField(blank=True, help_text='Note globale (0-20)', null=True)),
                ('commentaire', models.TextField(blank=True)),
                ('fidele', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='formations_inscrites', to='fidele.fidele')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='inscriptions', to='formation.formationsession')),
            ],
            options={'verbose_name': 'Inscription',
                     'verbose_name_plural': 'Inscriptions',
                     'ordering': ['-date_inscription'],
                     'unique_together': {('session', 'fidele')}},
        ),
        migrations.CreateModel(
            name='FormationPresence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('present', models.BooleanField(default=False)),
                ('excuse', models.CharField(blank=True, max_length=140)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('inscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='presences', to='formation.formationinscription')),
                ('module', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='presences', to='formation.formationmodule')),
            ],
            options={'verbose_name': 'Présence',
                     'verbose_name_plural': 'Présences',
                     'ordering': ['module__ordre'],
                     'unique_together': {('inscription', 'module')}},
        ),
    ]
