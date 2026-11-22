from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

LATEST = ('formation', '0003_merge_20261023')


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([target])


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


class FormationMigrationsTests(TransactionTestCase):
    """Le conflit des deux 0002 est résolu par 0003_merge, sans perte de données."""

    def test_graphe_sans_conflit(self):
        executor = MigrationExecutor(connection)
        self.assertEqual(executor.loader.detect_conflicts(), {})

    def test_base_creee_avec_ancienne_0001_colonne_format_(self):
        _migrate(('formation', '0001_initial'))
        try:
            # Simule une base créée par l'ancienne 0001 (colonne "format_") contenant une formation sans slug
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE formation_formation RENAME COLUMN "format" TO "format_"')
                cursor.execute(
                    "INSERT INTO formation_formation "
                    "(slug, nom, theme, description, duree_mois, format_, actif, created_at) "
                    "VALUES ('', 'Préparation au mariage', 'mariage', '', 3, 'En couple', true, now())"
                )
            _migrate(LATEST)
        finally:
            if 'format_' in _columns('formation_formation'):
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE formation_formation RENAME COLUMN "format_" TO "format"')
            _migrate(LATEST)

        columns = _columns('formation_formation')
        self.assertIn('format', columns)
        self.assertNotIn('format_', columns)
        with connection.cursor() as cursor:
            cursor.execute('SELECT "format", slug FROM formation_formation')
            fmt, slug = cursor.fetchone()
        self.assertEqual(fmt, 'En couple')  # donnée conservée
        self.assertEqual(slug, 'preparation-au-mariage')  # slug généré par 0002_auto_populate_slug
