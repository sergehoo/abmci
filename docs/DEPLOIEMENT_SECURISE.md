# Checklist de déploiement sécurisé — branche `securite/remediation-p0-p1`

Chaque étape marquée **[VALIDATION]** touche la production : elle n'est exécutée qu'après accord explicite.
Ne jamais coller une valeur secrète dans un ticket, un chat ou un commit.

## 0. Pré-requis (poste local)
- [ ] Tests ciblés verts sous Django 4.2 (version de l'image) :
      `python manage.py test api.test_securite fidele.test_backoffice formation.test_migrations`
- [ ] `python manage.py makemigrations --check --dry-run` : aucune migration en attente pour fidele, event, eden, formation
      (l'app tierce `recurrence` signale des `AlterField id` sous Django 4.2 : ne pas générer de migration pour elle).
- [ ] Image construite localement sans `.env` embarqué (`.dockerignore`).

## 1. Sauvegarde **[VALIDATION]**
- [ ] Dump de la base AVANT tout changement (hors volume Docker) :
      `docker exec abmcidb pg_dump -U postgres -Fc <DB_NAME> > /home/ubuntu/backups/abmci_$(date +%F_%H%M).dump`
- [ ] Vérifier le dump : `pg_restore --list <fichier> | head`
- [ ] Copie de `/var/www/abmci/media` et du `.env` serveur (stockage chiffré, accès restreint).
- [ ] Noter le commit actuellement déployé : `git -C <repo serveur> rev-parse HEAD` (point de rollback).

## 2. Adminer (immédiat) **[VALIDATION]**
- [ ] Arrêter le conteneur exposé : `docker stop abmci-adminer && docker rm abmci-adminer`
- [ ] Vérifier : `curl -sI https://adminer.abmci.com` ne doit plus répondre 200.
- [ ] Examiner les journaux Postgres/Adminer pour des connexions inconnues.
- [ ] Usage futur uniquement à la demande : `ADMINER_BASIC_AUTH` (sortie de `htpasswd -nbB <user> <mdp>`, entre apostrophes
      dans `.env`) puis `docker compose --profile tools up -d adminer`, arrêt après usage.

## 3. Rotation des secrets **[VALIDATION]** (valeurs générées et saisies par l'administrateur, jamais affichées)
- [ ] `SECRET_KEY` : nouvelle valeur (`python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"`).
      Effet : invalide tous les JWT, sessions et liens de réinitialisation.
- [ ] Mot de passe Postgres : `ALTER USER postgres WITH PASSWORD '…';` via `docker exec -it abmcidb psql -U postgres`,
      puis `DB_PASSWORD` dans `.env` (idéalement : utilisateur applicatif dédié non superuser).
- [ ] Mot de passe SMTP de contact@abmci.com (panneau Hostinger) → variables `EMAIL_*` du `.env`.
- [ ] Firebase (GCP IAM) : supprimer l'ancienne clé de compte de service (bloc commenté du `.env`,
      `static/abmci-62f4d-firebase.json`), régénérer la clé active, supprimer ces fichiers du serveur.
- [ ] Clé API Android (`static/google-services.json`) : restreindre à l'application Android dans GCP.
- [ ] Jeton DRF codé en dur dans l'app mobile conferencedabidjan.com : révoquer côté serveur concerné.
- [ ] Paystack : vérifier le type de clé (test/live) et l'URL du webhook `/api/paystack/webhook/` dans le dashboard.

## 4. Configuration production **[VALIDATION]**
- [ ] `.env` serveur : `DJANGO_ENV=prod` (ou retirer `DJANGO_ENV=dev`), `DEBUG` absent ou `False`.
- [ ] Variables requises présentes : `SECRET_KEY`, `DB_*`, `PAYSTACK_SECRET_KEY`, `EMAIL_*`, `FIREBASE_SERVICE_ACCOUNT_JSON`.
- [ ] Optionnel : `THROTTLE_AUTH_RATE`, `THROTTLE_QR_SCAN_RATE`.

## 5. Permissions staff (avant bascule, sinon perte d'accès au back-office) **[VALIDATION]**
- [ ] Lister les opérateurs : `python manage.py shell -c "from django.contrib.auth.models import User; print(list(User.objects.filter(is_staff=True).values_list('username', flat=True)))"`
- [ ] Donner `is_staff=True` aux opérateurs légitimes (admin Django), retirer les comptes inconnus.
- [ ] Permissions `fidele.*` (signalements, transfert, suppression) attribuées aux groupes concernés.

## 6. Migrations **[VALIDATION]**
- [ ] État avant : `python manage.py showmigrations formation fidele event`
- [ ] Plan : `python manage.py migrate --plan` — attendu : formation 0002×2 + 0003_merge, fidele 0002, event 0003.
- [ ] Les migrations ne suppriment aucune donnée (2 colonnes passent en NULL, renommage conditionnel de `format_`).

## 7. Déploiement **[VALIDATION]**
- [ ] `git fetch && git checkout <commit validé>` sur le serveur (bind mount `.:/app`).
- [ ] Reconstruire l'image (entrypoint modifié) : `docker compose build && docker compose up -d`
- [ ] Désactiver dans l'admin (django-celery-beat) les anciennes tâches `push_verse_of_day_daily` et
      `remind-stale-problems-every-hour` (elles restent en base).

## 8. Contrôles de santé
- [ ] `docker compose ps` : abmciweb `healthy` (sonde `/healthz`).
- [ ] `curl -s https://administration.abmci.com/une-url-inexistante` → 404 générique (pas de page de debug).
- [ ] `curl -s -o /dev/null -w '%{http_code}' -X POST https://administration.abmci.com/api/paystack/webhook/` → 401.
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://administration.abmci.com/api/fideles/` → 401 sans jeton.
- [ ] Connexion back-office d'un opérateur staff OK ; un compte fidèle reçoit 403 sur `/fidele/membres/`.
- [ ] App mobile : connexion, liste des prières, commentaire, profil, scan QR.
- [ ] Journaux : `docker compose logs --tail=200 abmciweb celery celery-beat` sans erreur.

## 9. Rollback
- [ ] Code : `git checkout <commit noté à l'étape 1>` puis `docker compose build && docker compose up -d`.
- [ ] Les migrations ajoutées sont compatibles avec l'ancien code (ajout de NULL / renommage conditionnel) : pas de retour
      arrière de schéma nécessaire. Si indispensable : `python manage.py migrate fidele 0001 event 0002 formation 0002_auto_populate_slug`
      (uniquement si aucune ligne n'a pris la valeur NULL).
- [ ] Données : restauration du dump de l'étape 1 (`pg_restore --clean -d <DB_NAME> <fichier>`) en dernier recours.
- [ ] Les secrets déjà changés ne doivent pas être restaurés à leurs anciennes valeurs (compromises).
