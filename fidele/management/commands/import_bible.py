import hashlib
import os
import re
from typing import Iterable, List, Tuple

from django.core.management.base import BaseCommand
from django.db import transaction

from fidele.models import BibleVersion, BibleVerse

# Mapping VPL (codes 3 lettres) -> noms FR
BOOK_MAP_FR = {
    "GEN": "Genèse",
    "EXO": "Exode",
    "LEV": "Lévitique",
    "NUM": "Nombres",
    "DEU": "Deutéronome",
    "JOS": "Josué",
    "JDG": "Juges",
    "RUT": "Ruth",
    "1SA": "1 Samuel",
    "2SA": "2 Samuel",
    "1KI": "1 Rois",
    "2KI": "2 Rois",
    "1CH": "1 Chroniques",
    "2CH": "2 Chroniques",
    "EZR": "Esdras",
    "NEH": "Néhémie",
    "EST": "Esther",
    "JOB": "Job",
    "PSA": "Psaumes",
    "PRO": "Proverbes",
    "ECC": "Ecclésiaste",
    "SNG": "Cantique des Cantiques",
    "ISA": "Ésaïe",
    "JER": "Jérémie",
    "LAM": "Lamentations",
    "EZK": "Ézéchiel",
    "DAN": "Daniel",
    "HOS": "Osée",
    "JOL": "Joël",
    "AMO": "Amos",
    "OBA": "Abdias",
    "JON": "Jonas",
    "MIC": "Michée",
    "NAM": "Nahum",
    "HAB": "Habacuc",
    "ZEP": "Sophonie",
    "HAG": "Aggée",
    "ZEC": "Zacharie",
    "MAL": "Malachie",
    "MAT": "Matthieu",
    "MRK": "Marc",
    "LUK": "Luc",
    "JHN": "Jean",
    "ACT": "Actes",
    "ROM": "Romains",
    "1CO": "1 Corinthiens",
    "2CO": "2 Corinthiens",
    "GAL": "Galates",
    "EPH": "Éphésiens",
    "PHP": "Philippiens",
    "COL": "Colossiens",
    "1TH": "1 Thessaloniciens",
    "2TH": "2 Thessaloniciens",
    "1TI": "1 Timothée",
    "2TI": "2 Timothée",
    "TIT": "Tite",
    "PHM": "Philémon",
    "HEB": "Hébreux",
    "JAS": "Jacques",
    "1PE": "1 Pierre",
    "2PE": "2 Pierre",
    "1JN": "1 Jean",
    "2JN": "2 Jean",
    "3JN": "3 Jean",
    "JUD": "Jude",
    "REV": "Apocalypse",
}

# Regex VPL : 7 champs, tous entre guillemets
# ("GN1_1","002_1_1","GEN","1","1","1","Au commencement…");
VPL_ROW_RE = re.compile(
    r'INSERT\s+INTO\s+verses\s+VALUES\s*\(\s*'
    r'"([^"]*)"\s*,\s*'    # verseID (ex: GN1_1) -> g1
    r'"([^"]*)"\s*,\s*'    # canon_order        -> g2
    r'"([^"]*)"\s*,\s*'    # book code (GEN)    -> g3
    r'"([^"]*)"\s*,\s*'    # chapter            -> g4
    r'"([^"]*)"\s*,\s*'    # startVerse         -> g5
    r'"([^"]*)"\s*,\s*'    # endVerse           -> g6
    r'"([^"]*)"\s*'        # verseText          -> g7
    r'\)\s*;?'
)

def iter_vpl_rows(sql_text: str) -> Iterable[Tuple[str, str, str, str, str, str, str]]:
    """
    Itère sur chaque INSERT VPL et renvoie les 7 champs sous forme de tuple de str.
    """
    for m in VPL_ROW_RE.finditer(sql_text):
        yield m.groups()  # (verseID, canon, book_code, chapter, start, end, text)


class Command(BaseCommand):
    help = "Importe un fichier VPL (fraLSG_vpl.sql) dans BibleVersion/BibleVerse"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Chemin vers le fichier SQL VPL (ex: static/fraLSG_vpl.sql)",
        )
        parser.add_argument(
            "--version-code",
            type=str,
            required=True,
            help="Code de la version (ex: LSG)",
        )
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help='Nom de la version (ex: "Louis Segond 1910")',
        )
        parser.add_argument(
            "--language",
            type=str,
            default="fr",
            help="Langue (par défaut: fr)",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Supprime les versets existants de cette version avant import",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=5000,
            help="Taille des lots pour bulk_create (par défaut: 5000)",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        file_path: str = opts["file"]
        code: str = opts["version_code"]
        name: str = opts["name"]
        language: str = opts["language"]
        replace: bool = opts["replace"]
        batch_size: int = opts["batch_size"]

        if not os.path.exists(file_path):
            self.stderr.write(self.style.ERROR(f"Fichier introuvable: {file_path}"))
            return

        # Charge le fichier
        with open(file_path, "r", encoding="utf-8") as f:
            sql_text = f.read()

        # ETag basé sur le contenu -> permet de savoir s'il faut resynchroniser côté client
        etag = hashlib.md5(sql_text.encode("utf-8")).hexdigest()

        # Crée/MAJ la version
        version, created = BibleVersion.objects.get_or_create(
            code=code,
            defaults={"name": name, "language": language, "etag": etag},
        )
        if not created:
            # met à jour le nom/lang/lang et etag si besoin
            changed = False
            if version.name != name:
                version.name = name
                changed = True
            if version.language != language:
                version.language = language
                changed = True
            if version.etag != etag:
                version.etag = etag
                changed = True
            if changed:
                version.save()
            self.stdout.write(self.style.WARNING(f"Version existante: {version.code}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Version créée: {version.code}"))

        if replace:
            deleted = BibleVerse.objects.filter(version=version).delete()[0]
            self.stdout.write(self.style.WARNING(f"Versets supprimés (ancienne version): {deleted}"))

        # Parse & préparer les instances
        to_create: List[BibleVerse] = []
        count = 0
        for verse_id, canon, book_code, chapter, start_v, end_v, verse_text in iter_vpl_rows(sql_text):
            # mappe le livre
            book_name = BOOK_MAP_FR.get(book_code, book_code)

            # VPL peut contenir des plages (ex: 3-4) ; on prend startVerse comme verset
            try:
                ch = int(chapter)
                vs = int(start_v)
            except ValueError:
                # Si non numérique, on saute proprement
                continue

            to_create.append(
                BibleVerse(
                    version=version,
                    book=book_name,
                    chapter=ch,
                    verse=vs,
                    text=verse_text.strip(),
                )
            )
            # Bulk par batch
            if len(to_create) >= batch_size:
                BibleVerse.objects.bulk_create(to_create, ignore_conflicts=True)
                count += len(to_create)
                to_create.clear()
                self.stdout.write(f"... {count} versets importés")

        # Flush final
        if to_create:
            BibleVerse.objects.bulk_create(to_create, ignore_conflicts=True)
            count += len(to_create)

        # Recalcule le total
        version.total_verses = version.verses.count()
        version.save(update_fields=["total_verses", "etag", "updated_at"])

        self.stdout.write(self.style.SUCCESS(
            f"Import terminé : {count} insérés (total={version.total_verses}, etag={version.etag})"
        ))