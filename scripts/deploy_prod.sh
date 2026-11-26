#!/usr/bin/env bash
# Déploiement production ABMCI — suit docs/DEPLOIEMENT_SECURISE.md.
# À lancer SUR LE SERVEUR, depuis le dossier du dépôt (celui monté en .:/app par docker-compose) :
#   bash scripts/deploy_prod.sh <commit-ou-branche>
# Le script n'affiche aucun secret et demande confirmation avant chaque étape critique.
set -euo pipefail

TARGET="${1:?Usage : bash scripts/deploy_prod.sh <commit-ou-branche>}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/abmci}"
DOMAIN="${DOMAIN:-https://administration.abmci.com}"
STAMP="$(date +%F_%H%M%S)"
MANAGE=(docker compose run --rm -T -e RUN_MIGRATIONS=0 -e COLLECTSTATIC=skip abmciweb python manage.py)

step() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[ATTENTION]\033[0m %s\n' "$*"; }
confirm() { read -r -p "$1 [o/N] " r; [[ "$r" =~ ^[oOyY]$ ]] || { echo "Arrêt demandé : rien d'autre n'a été modifié."; exit 1; }; }
has_value() { grep -qE "^$1=.+" .env; }  # vérifie la présence d'une variable sans afficher sa valeur

[ -f .env ] && [ -f docker-compose.yml ] || { echo "Lancer depuis le dossier du dépôt (avec .env et docker-compose.yml)."; exit 1; }

step "0. Point de retour"
PREV_COMMIT="$(git rev-parse HEAD)"
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
echo "$PREV_COMMIT" > "$BACKUP_DIR/commit_avant_$STAMP.txt"
ok "Commit actuellement déployé : $PREV_COMMIT (noté dans $BACKUP_DIR)"

step "1. Sauvegarde (base, media, .env)"
docker exec abmcidb sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$BACKUP_DIR/abmci_$STAMP.dump"
docker exec -i abmcidb pg_restore --list < "$BACKUP_DIR/abmci_$STAMP.dump" > /dev/null
ok "Dump vérifié : $BACKUP_DIR/abmci_$STAMP.dump ($(du -h "$BACKUP_DIR/abmci_$STAMP.dump" | cut -f1))"
if [ -d /var/www/abmci/media ]; then
  tar czf "$BACKUP_DIR/media_$STAMP.tgz" -C /var/www/abmci media && ok "Media sauvegardés"
fi
install -m 600 .env "$BACKUP_DIR/env_$STAMP" && ok ".env sauvegardé (droits 600)"

step "2. Adminer (exposé publiquement)"
if docker ps -a --format '{{.Names}}' | grep -qx abmci-adminer; then
  docker stop abmci-adminer >/dev/null && docker rm abmci-adminer >/dev/null && ok "Adminer arrêté et supprimé"
else
  ok "Adminer déjà arrêté"
fi

step "3. Rotation des secrets (manuelle, valeurs jamais affichées)"
echo "À faire par l'administrateur AVANT de continuer (cf. checklist §3) :"
echo "  - SECRET_KEY (déconnecte tous les utilisateurs), mot de passe Postgres + DB_PASSWORD,"
echo "  - mot de passe SMTP contact@abmci.com, clés de compte de service Firebase (GCP)."
confirm "Les secrets ont-ils été changés et reportés dans .env ?"

step "4. Configuration production"
for v in SECRET_KEY DB_NAME DB_USER DB_PASSWORD DB_HOST; do
  has_value "$v" || { echo "Variable $v absente ou vide dans .env"; exit 1; }
done
ok "Variables requises présentes"
if grep -qE '^DJANGO_ENV=prod$' .env; then
  ok "DJANGO_ENV=prod"
else
  warn "DJANGO_ENV n'est pas « prod » (le serveur tourne en DEBUG)."
  confirm "Passer DJANGO_ENV=prod et DEBUG=False dans .env ?"
  sed -i -E '/^DJANGO_ENV=/d; /^DEBUG=/d' .env
  printf 'DJANGO_ENV=prod\nDEBUG=False\n' >> .env
  ok "DJANGO_ENV=prod, DEBUG=False"
fi

step "5. Code"
git fetch --all --prune
# Migrations générées sur le serveur (non suivies par git) que le dépôt apporte sous le même nom :
# elles sont mises de côté (la base les a déjà appliquées ; Django se fie aux noms, vérifié à l'étape 8).
MIG_BACKUP="$BACKUP_DIR/migrations_serveur_$STAMP"
CONFLITS="$(comm -12 <(git ls-files --others --exclude-standard | sort) <(git ls-tree -r --name-only "$TARGET" | sort) || true)"
if [ -n "$CONFLITS" ]; then
  echo "Fichiers non suivis qui seraient écrasés :"; echo "$CONFLITS" | sed 's/^/  - /'
  confirm "Les déplacer dans $MIG_BACKUP (restaurables) ?"
  mkdir -p "$MIG_BACKUP"
  while IFS= read -r f; do mkdir -p "$MIG_BACKUP/$(dirname "$f")" && mv "$f" "$MIG_BACKUP/$f"; done <<< "$CONFLITS"
  ok "Fichiers déplacés dans $MIG_BACKUP"
fi
git checkout --detach "$TARGET"
ok "Code positionné sur $(git log --oneline -1)"

step "6. Image Docker (entrypoint modifié → reconstruction obligatoire)"
docker compose build abmciweb celery celery-beat
ok "Images construites"

step "7. Comptes staff (accès au back-office désormais réservé au staff)"
"${MANAGE[@]}" shell -c "from django.contrib.auth.models import User
for u in User.objects.filter(is_staff=True).order_by('username'):
    print(' -', u.username, '(superuser)' if u.is_superuser else '(staff)')"
echo "Pour ajouter un opérateur : ${MANAGE[*]} shell -c \"from django.contrib.auth.models import User; User.objects.filter(username='NOM').update(is_staff=True)\""
confirm "Tous les opérateurs du back-office figurent-ils dans cette liste ?"

step "8. Migrations (contrôle du schéma réel puis du plan)"
SCHEMA="$("${MANAGE[@]}" shell < scripts/verif_schema.py 2>&1 | tail -n 40)"
echo "$SCHEMA"
echo "$SCHEMA" | grep -q "^SCHEMA_OK" || { echo "Écart entre les modèles et la base : arrêt avant toute migration (rollback : étape ROLLBACK ci-dessous)."; exit 1; }
ok "Modèles fidele/event/eden conformes au schéma de production"
PLAN="$("${MANAGE[@]}" migrate --plan 2>&1)"
echo "$PLAN"
ATTENDUES='^(event\.0003_proteger_eglise_type_evenement|fidele\.0002_securiser_suppressions_cascade|fidele\.0003_retirer_photo_par_defaut|formation\.0001_initial|formation\.0002_auto_populate_slug|formation\.0002_rename_format__formation_format_and_more|formation\.0003_merge_20261023)$'
INATTENDUES="$(echo "$PLAN" | grep -oE '^[a-z_]+\.[0-9]{4}_[A-Za-z0-9_]+' | grep -vE "$ATTENDUES" || true)"
if [ -n "$INATTENDUES" ]; then
  warn "Migrations non prévues dans le plan :"; echo "$INATTENDUES" | sed 's/^/  - /'
  confirm "Les examiner a été fait et vous voulez quand même continuer ?"
else
  ok "Plan conforme : uniquement les migrations attendues (aucune suppression de données)"
fi
confirm "Appliquer ces migrations et redémarrer les services ?"

step "9. Redémarrage (l'entrypoint de abmciweb applique les migrations)"
docker compose up -d abmciweb celery celery-beat
for i in $(seq 1 40); do
  s="$(docker inspect -f '{{.State.Health.Status}}' abmciweb 2>/dev/null || echo inconnu)"
  [ "$s" = healthy ] && break
  sleep 5
done
[ "$s" = healthy ] && ok "abmciweb healthy" || warn "abmciweb : état « $s » (voir : docker compose logs --tail=200 abmciweb)"

step "10. Contrôles de santé"
check() {  # description, code attendu, commande curl…
  local desc="$1" expected="$2"; shift 2
  local code; code="$(curl -s -o /dev/null -w '%{http_code}' "$@" || true)"
  if [ "$code" = "$expected" ]; then ok "$desc → $code"; else warn "$desc → $code (attendu $expected)"; FAILED=1; fi
}
FAILED=0
check "Page inexistante (404 générique, pas de debug)" 404 "$DOMAIN/une-url-inexistante-$STAMP"
if curl -s "$DOMAIN/une-url-inexistante-$STAMP" | grep -q "DEBUG = True"; then warn "La page 404 expose encore le mode DEBUG"; FAILED=1; fi
check "Webhook Paystack sans signature" 401 -X POST "$DOMAIN/api/paystack/webhook/"
check "/api/fideles/ sans jeton" 401 "$DOMAIN/api/fideles/"
check "/api/annuaire/ sans jeton (route déployée)" 401 "$DOMAIN/api/annuaire/"
check "Calendrier sans connexion → login" 302 "$DOMAIN/evenements/calendrier"
check "Adminer" 404 "https://adminer.abmci.com/"
docker compose logs --tail=50 abmciweb celery celery-beat 2>&1 | grep -iE "error|exception|traceback" | tail -5 || true

step "Fin"
if [ "$FAILED" = 0 ]; then ok "Déploiement terminé et contrôles verts."; else warn "Contrôles à examiner (voir ci-dessus)."; fi
cat <<EOF

À faire maintenant dans l'admin Django :
  - django-celery-beat : désactiver « push_verse_of_day_daily » et « remind-stale-problems-every-hour »
  - Demandes de suppression de compte : action « Supprimer définitivement… »
Tests manuels : connexion d'un opérateur au back-office, puis app mobile (connexion, prières, profil, annuaire).

ROLLBACK si nécessaire :
  git checkout --detach $PREV_COMMIT && cp -r $BACKUP_DIR/migrations_serveur_$STAMP/. . 2>/dev/null; docker compose build abmciweb celery celery-beat && docker compose up -d abmciweb celery celery-beat
  (migrations compatibles avec l'ancien code ; en dernier recours :
   docker exec -i abmcidb sh -c 'pg_restore --clean -U "\$POSTGRES_USER" -d "\$POSTGRES_DB"' < $BACKUP_DIR/abmci_$STAMP.dump)
  Ne jamais remettre les anciens secrets (compromis).
EOF
