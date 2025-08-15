import hashlib
import os
import re
from typing import Iterable, Iterator, List, Tuple

from django.core.management.base import BaseCommand
from django.db import transaction

from fidele.models import BibleVersion, BibleVerse

# ----------------------------------
# Mapping VPL (codes 3 lettres) -> noms FR
# (avec quelques alias/variantes rencontrées)
# ----------------------------------
BOOK_MAP_FR = {
    # AT
    "GEN": "Genèse", "EXO": "Exode", "LEV": "Lévitique", "NUM": "Nombres", "DEU": "Deutéronome",
    "JOS": "Josué", "JDG": "Juges", "RUT": "Ruth",
    "1SA": "1 Samuel", "2SA": "2 Samuel",
    "1KI": "1 Rois", "2KI": "2 Rois",
    "1CH": "1 Chroniques", "2CH": "2 Chroniques",
    "EZR": "Esdras", "NEH": "Néhémie", "EST": "Esther",
    "JOB": "Job", "PSA": "Psaumes", "PRO": "Proverbes",
    "ECC": "Ecclésiaste", "SNG": "Cantique des Cantiques",
    "ISA": "Ésaïe", "JER": "Jérémie", "LAM": "Lamentations",
    "EZE": "Ézéchiel", "EZK": "Ézéchiel",  # alias
    "DAN": "Daniel",
    "HOS": "Osée", "JOL": "Joël", "AMO": "Amos", "OBA": "Abdias",
    "JON": "Jonas", "MIC": "Michée", "NAM": "Nahum", "HAB": "Habacuc",
    "ZEP": "Sophonie", "HAG": "Aggée", "ZEC": "Zacharie", "MAL": "Malachie",
    # NT
    "MAT": "Matthieu", "MRK": "Marc", "LUK": "Luc", "JHN": "Jean",
    "ACT": "Actes", "ROM": "Romains",
    "1CO": "1 Corinthiens", "2CO": "2 Corinthiens",
    "GAL": "Galates", "EPH": "Éphésiens", "PHP": "Philippiens", "COL": "Colossiens",
    "1TH": "1 Thessaloniciens", "2TH": "2 Thessaloniciens",
    "1TI": "1 Timothée", "2TI": "2 Timothée",
    "TIT": "Tite", "PHM": "Philémon", "HEB": "Hébreux",
    "JAS": "Jacques", "1PE": "1 Pierre", "2PE": "2 Pierre",
    "1JN": "1 Jean", "2JN": "2 Jean", "3JN": "3 Jean",
    "JUD": "Jude",
    "REV": "Apocalypse", "APO": "Apocalypse",  # alias
}

# ----------------------------------
# REGEX VPL : 7 champs, tous entre guillemets
# INSERT INTO <anytable> VALUES ("GN1_1","002_1_1","GEN","1","1","1","Texte");
# ----------------------------------
VPL_ROW_RE = re.compile(
    r'INSERT\s+INTO\s+[A-Za-z0-9_]+\s+VALUES\s*'
    r'\(\s*'
    r'"([^"]*)"\s*,\s*'      # verseID          -> g1 (ignoré)
    r'"([^"]*)"\s*,\s*'      # canon_order      -> g2 (ignoré)
    r'"([A-Z0-9]{3})"\s*,\s*'# book code (ex: GEN) -> g3
    r'"(\d+)"\s*,\s*'        # chapter          -> g4
    r'"(\d+)"\s*,\s*'        # startVerse       -> g5
    r'"(\d+)"\s*,\s*'        # endVerse         -> g6
    r'"((?:[^"\\]|\\.)*)"\s*'# verseText (échappé) -> g7
    r'\)\s*;?',
    re.IGNORECASE
)

# Ancien format : (id,'Livre',chap,verset,'Texte')
OLD_ROW_RE = re.compile(
    r'\(\s*\d+\s*,\s*\'([^\']+)\'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*\'([^\']*)\'\s*\)'
)

def _unescape_sql_text(s: str) -> str:
    # gère \" et \' laissés dans certains dumps
    return s.replace(r'\"', '"').replace(r"\'", "'").strip()

def _iter_vpl(sql_text: str) -> Iterator[Tuple[str, int, int, str]]:
    """
    Rend (book_fr, chapter, verse, text) depuis un dump VPL.
    Duplique le texte si startVerse..endVerse couvre une plage.
    """
    for m in VPL_ROW_RE.finditer(sql_text):
        book_code = m.group(3).upper()
        book_fr = BOOK_MAP_FR.get(book_code)
        if not book_fr:
            # Inconnu : on saute
            continue
        chapter = int(m.group(4))
        v1 = int(m.group(5))
        v2 = int(m.group(6))
        if v2 < v1:
            v2 = v1
        text = _unescape_sql_text(m.group(7))
        for v in range(v1, v2 + 1):
            yield (book_fr, chapter, v, text)

def _iter_old(sql_text: str) -> Iterator[Tuple[str, int, int, str]]:
    """
    Rend (book_fr, chapter, verse, text) pour l'ancien format.
    """
    for m in OLD_ROW_RE.finditer(sql_text):
        book_fr = m.group(1).strip()
        chapter = int(m.group(2))
        verse = int(m.group(3))
        text = _unescape_sql_text(m.group(4))
        yield (book_fr, chapter, verse, text)

class Command(BaseCommand):
    help = "Synchronise une version biblique (fichier .sql au format VPL ou ancien format) dans BibleVersion/BibleVerse."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Chemin du dump SQL (ex: static/frajnd_vpl.sql)")
        parser.add_argument("--version-code", required=True, help="Code de version (ex: LSG, JND, BDS...)")
        parser.add_argument("--name", required=True, help='Nom complet (ex: "Louis Segond 1910")')
        parser.add_argument("--language", default="fr", help="Langue (défaut: fr)")
        parser.add_argument("--truncate", action="store_true",
                            help="Purge d’abord tous les versets de cette version (full replace).")
        parser.add_argument("--force", action="store_true",
                            help="Ignore l’etag et réimporte même si le fichier est inchangé.")
        parser.add_argument("--mode", choices=["insert", "upsert"], default="insert",
                            help="insert (rapide, ignore duplicats) ou upsert (met à jour le texte existant).")
        parser.add_argument("--batch-size", type=int, default=5000, help="Taille des lots pour bulk (défaut: 5000)")

    @transaction.atomic
    def handle(self, *args, **opts):
        path: str = opts["file"]
        code: str = opts["version_code"]
        name: str = opts["name"]
        lang: str = opts["language"]
        truncate: bool = opts["truncate"]
        force: bool = opts["force"]
        mode: str = opts["mode"]
        batch_size: int = opts["batch_size"]

        if not os.path.exists(path):
            self.stderr.write(self.style.ERROR(f"Fichier introuvable: {path}"))
            return

        raw = open(path, "rb").read()
        sql_text = raw.decode("utf-8", errors="ignore")
        etag = hashlib.md5(raw).hexdigest()

        # 1) Version
        version, created = BibleVersion.objects.get_or_create(
            code=code,
            defaults={"name": name, "language": lang, "etag": etag},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Version créée: {version.code}"))
        else:
            # MAJ meta si changé
            changed = False
            if version.name != name:
                version.name = name; changed = True
            if version.language != lang:
                version.language = lang; changed = True
            if version.etag != etag and not force:
                # Même si meta diffère, si on ne force pas et que le contenu est identique, on skippera plus bas
                pass
            if changed:
                version.save()

        # 2) etag check
        if (version.etag == etag) and (not force) and (not truncate):
            self.stdout.write(self.style.WARNING(
                f"Aucun changement détecté (etag identique). Utilise --force pour forcer."
            ))
            self.stdout.write(self.style.SUCCESS(
                f"Import terminé : 0 insérés (total={version.verses.count()}, etag={version.etag})"
            ))
            return

        # 3) purge si demandé
        if truncate:
            deleted = BibleVerse.objects.filter(version=version).delete()[0]
            self.stdout.write(self.style.WARNING(f"Purge: {deleted} versets supprimés."))

        # 4) sélection du parser (VPL vs ancien)
        parser_iter: Iterable[Tuple[str, int, int, str]]
        if VPL_ROW_RE.search(sql_text):
            parser_iter = _iter_vpl(sql_text)
        else:
            parser_iter = _iter_old(sql_text)

        inserted = 0
        updated = 0

        # 5a) mode INSERT (rapide, ignore duplicats)
        if mode == "insert":
            batch: List[BibleVerse] = []
            for book, ch, vs, txt in parser_iter:
                batch.append(BibleVerse(
                    version=version, book=book, chapter=ch, verse=vs, text=txt
                ))
                if len(batch) >= batch_size:
                    BibleVerse.objects.bulk_create(batch, ignore_conflicts=True)
                    inserted += len(batch)
                    batch.clear()
            if batch:
                BibleVerse.objects.bulk_create(batch, ignore_conflicts=True)
                inserted += len(batch)

        # 5b) mode UPSERT (plus lent : met à jour si existe)
        else:  # upsert
            # On fait des paquets pour limiter les hits
            to_create: List[BibleVerse] = []
            for book, ch, vs, txt in parser_iter:
                obj, created_v = BibleVerse.objects.update_or_create(
                    version=version, book=book, chapter=ch, verse=vs,
                    defaults={"text": txt}
                )
                if created_v:
                    inserted += 1
                else:
                    updated += 1

        # 6) recalc & MAJ etag
        version.total_verses = version.verses.count()
        version.etag = etag
        version.save(update_fields=["total_verses", "etag", "updated_at"])

        self.stdout.write(self.style.SUCCESS(
            f"Import terminé : {inserted} insérés"
            + (f", {updated} MAJ" if updated else "")
            + f" (total={version.total_verses}, etag={etag})"
        ))