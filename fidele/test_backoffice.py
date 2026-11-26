"""Tests ciblés : contrôle d'accès du back-office, XSS, suppressions en cascade et vues réparées."""
import shutil
import tempfile
from unittest import mock

from django.contrib.messages.storage.base import Message
from django.db.models import ProtectedError
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from abmci.factories import fidele_of, make_eglise, make_user
from event.models import Evenement
from fidele.form import ProfileCompletionForm
from fidele.models import Eglise, Fidele, Notification, NotificationUser, ProblemReport

# Evenement.save() génère un QR code : les fichiers des tests ne doivent pas atterrir dans media/ du dépôt
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="abmci-test-media-")


def tearDownModule():
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class BackOfficeAccessTests(TestCase):
    def setUp(self):
        self.fidele_user = make_user("fidele_simple")
        self.staff = make_user("operateur", staff=True)

    def test_vues_de_gestion_refusees_aux_comptes_non_staff(self):
        self.client.force_login(self.fidele_user)
        for url in (reverse("membres"), reverse("donation-list"), reverse("fiancailles-list"),
                    reverse("event-list"), reverse("event-calend"), reverse("formations_index"),
                    reverse("pastorale_index"), reverse("home")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonyme_redirige_vers_la_connexion(self):
        for url in (reverse("membres"), reverse("evenement_create"), reverse("event-calend")):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 302)
                self.assertIn("login", r["Location"])

    def test_evenement_non_modifiable_sans_authentification(self):
        ev = Evenement.objects.create(titre="Culte", lieu="Temple", description="d")
        r = self.client.post(reverse("evenement_update", args=[ev.pk]), {"titre": "Pirate"})
        self.assertEqual(r.status_code, 302)
        ev.refresh_from_db()
        self.assertEqual(ev.titre, "Culte")

    def test_permanence_sans_authentification_refusee(self):
        self.assertEqual(self.client.post(reverse("createpermanence", args=[1])).status_code, 302)

    def test_staff_accede_au_back_office(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("membres")).status_code, 200)
        self.assertEqual(self.client.get(reverse("event-calend")).status_code, 200)

    def test_suppression_de_compte_reste_accessible_aux_fideles(self):
        self.client.force_login(self.fidele_user)
        self.assertEqual(self.client.get(reverse("account_delete")).status_code, 200)
        self.assertEqual(self.client.get(reverse("account_delete_done")).status_code, 200)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class XssTests(TestCase):
    def test_calendrier_echappe_les_donnees_des_evenements(self):
        staff = make_user("staff_cal", staff=True)
        Evenement.objects.create(titre="</script><script>alert(1)</script>", lieu="x", description="d")
        self.client.force_login(staff)
        r = self.client.get(reverse("event-calend"))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b"<script>alert(1)</script>", r.content)
        self.assertIn(b"\\u003C/script\\u003E", r.content)

    def test_toast_sans_template_literal_injectable(self):
        request = RequestFactory().get("/")
        request.user = make_user("toast")
        html = render_to_string("layout/base.html", {
            "messages": [Message(20, "Bonjour ${alert(1)} `x` 'y'")],
        }, request=request)
        # Chaîne entre apostrophes (pas de template literal : « ${…} » y reste du texte inerte)
        self.assertNotIn("text: `", html)
        self.assertIn("text: 'Bonjour ${alert(1)} \\u0060x\\u0060 \\u0027y\\u0027'", html)


class CascadeTests(TestCase):
    def test_supprimer_un_fidele_ne_supprime_pas_son_conjoint(self):
        a, b = make_user("epoux"), make_user("epouse")
        fa, fb = fidele_of(a), fidele_of(b)
        fa.marie_a = fb
        fa.save()
        fb.marie_a = fa
        fb.save()
        a.delete()
        fb.refresh_from_db()
        self.assertIsNone(fb.marie_a_id)

    def test_supprimer_une_eglise_avec_des_fideles_est_bloque(self):
        eglise = make_eglise()
        f = fidele_of(make_user("membre"))
        f.eglise = eglise
        f.save()
        with self.assertRaises(ProtectedError):
            eglise.delete()
        self.assertTrue(Fidele.objects.filter(pk=f.pk).exists())


class VuesRepareesTests(TestCase):
    def setUp(self):
        self.staff = make_user("staff_rep", staff=True)
        self.client.force_login(self.staff)

    def test_est_nouveau_sans_date_entree(self):
        f = fidele_of(make_user("sans_date"))
        f.date_entree = None
        self.assertFalse(f.est_nouveau)

    def test_recherche_texte_des_fideles(self):
        make_user("chercher", email="cible@example.com")
        r = self.client.get(reverse("membres"), {"q": "cible@example"})
        self.assertEqual(r.status_code, 200)

    def test_onglet_engagement_limite_au_fidele(self):
        f = fidele_of(make_user("onglet"))
        make_user("autre")
        r = self.client.get(reverse("engagement", args=[f.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.context["object_list"]), [f])

    def test_creation_web_d_un_fidele(self):
        r = self.client.post(reverse("fidele_create"), {
            "first_name": "Jean", "last_name": "Yao", "email": "jean.yao@example.com",
            "location": 1, "profession": "Comptable",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        f = Fidele.objects.get(user__email="jean.yao@example.com")
        self.assertEqual(f.profession, "Comptable")

    @mock.patch("fidele.views.send_mail")
    def test_transfert_d_un_fidele(self, send_mail):
        self.staff.is_superuser = True
        self.staff.save()
        e1, e2 = make_eglise("Cocody"), make_eglise("Yopougon")
        f = fidele_of(make_user("transfere"))
        f.eglise = e1
        f.save()
        r = self.client.post(reverse("fidele_transfer", args=[f.pk]), {"nouvelle_eglise": e2.pk, "motif": "Déménagement"})
        self.assertEqual(r.status_code, 302)
        f.refresh_from_db()
        self.assertEqual(f.eglise, e2)

    def test_suppression_logique_d_un_signalement(self):
        self.staff.is_superuser = True
        self.staff.save()
        eglise = make_eglise()
        pr = ProblemReport.objects.create(eglise=eglise, reporter=fidele_of(self.staff), title="Fuite",
                                          description="Toit")
        r = self.client.post(reverse("problemreport_delete", args=[pr.pk]))
        self.assertEqual(r.status_code, 302)
        pr.refresh_from_db()  # la ligne existe toujours
        self.assertTrue(pr.is_deleted)

    def test_notifications_web(self):
        notif = Notification.objects.create(type="TEST", title="Bienvenue", body="Message",
                                            data={"url": "https://exemple-externe.com/"})
        entry = NotificationUser.objects.create(user=self.staff, notification=notif)
        self.assertEqual(self.client.get(reverse("all")).status_code, 200)
        r = self.client.get(reverse("mark_read", args=[entry.pk]), {"next": "https://exemple-externe.com/"})
        self.assertEqual(r["Location"], reverse("all"))  # pas de redirection ouverte
        entry.refresh_from_db()
        self.assertTrue(entry.is_read)


class ProfileCompletionFormTests(TestCase):
    def test_etape_pre_remplie_et_options_non_partagees(self):
        f = fidele_of(make_user("profil"))
        f.profession = "Pasteur"
        f.save()
        form = ProfileCompletionForm(instance=f, step="2")
        self.assertEqual(form.initial.get("profession"), "Pasteur")
        self.assertEqual(ProfileCompletionForm._meta.fields, [])  # la classe n'est pas modifiée

    def test_champs_d_administration_absents(self):
        f = fidele_of(make_user("profil5"))
        form = ProfileCompletionForm(instance=f, step=5)
        for champ in ("membre", "type_membre", "fonction", "departement"):
            self.assertNotIn(champ, form.fields)


class SuperuserSansStaffTests(TestCase):
    def test_superuser_non_staff_accede_et_page_403_explicite(self):
        su = make_user("super_sans_staff")
        su.is_superuser = True
        su.is_staff = False
        su.save()
        self.client.force_login(su)
        self.assertEqual(self.client.get(reverse("membres")).status_code, 200)

        self.client.force_login(make_user("simple_fidele"))
        r = self.client.get(reverse("membres"))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Accès réservé à l'équipe de gestion", status_code=403)


class FichiersServisEnProdTests(TestCase):
    """Sans nginx devant Django, /media/ et /static/ doivent répondre même avec DEBUG=False."""

    def test_media_et_static_servis_sans_debug(self):
        import os
        media = tempfile.mkdtemp(prefix="abmci-test-media-")
        static_root = tempfile.mkdtemp(prefix="abmci-test-static-")
        try:
            os.makedirs(os.path.join(media, "banners"))
            with open(os.path.join(media, "banners", "a.png"), "wb") as f:
                f.write(b"\x89PNG\r\n")
            with open(os.path.join(static_root, "app.css"), "w") as f:
                f.write("body{}")
            with self.settings(DEBUG=False, MEDIA_ROOT=media, STATIC_ROOT=static_root):
                from django.urls import clear_url_caches
                import importlib, abmci.urls
                clear_url_caches()
                importlib.reload(abmci.urls)
                self.assertEqual(self.client.get("/media/banners/a.png").status_code, 200)
                self.assertEqual(self.client.get("/static/app.css").status_code, 200)
                self.assertIn(self.client.get("/media/../settings.py").status_code, (400, 404))  # traversée refusée
        finally:
            shutil.rmtree(media, ignore_errors=True)
            shutil.rmtree(static_root, ignore_errors=True)
            from django.urls import clear_url_caches
            import importlib, abmci.urls
            clear_url_caches()
            importlib.reload(abmci.urls)


class VersetDuJourTests(TestCase):
    @mock.patch("abmci.tasks.send_verse_to_eglise_topic", create=True)
    def test_verset_genere_meme_avec_un_evenement_recent(self, _push):
        from abmci.tasks import update_daily_verses_for_all_eglisess
        from fidele.models import BibleVerse, BibleVersion, VerseOfDay
        version = BibleVersion.objects.create(code="LSG", name="Louis Segond 1910")
        for v in range(1, 6):
            BibleVerse.objects.create(version=version, book="Jean", chapter=3, verse=v,  # 40 à 240 caractères requis
                                      text=f"Car Dieu a tant aimé le monde qu’il a donné son Fils unique ({v}).")
        eglise = make_eglise("Cathédrale")
        now = timezone.now()
        with override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT):
            Evenement.objects.create(titre="Culte", lieu="T", description="d", eglise=eglise,
                                     date_debut=now - timezone.timedelta(days=1),
                                     date_fin=now - timezone.timedelta(hours=20))
        self.assertEqual(update_daily_verses_for_all_eglisess(), 1)
        self.assertTrue(VerseOfDay.objects.filter(eglise=eglise, date=timezone.localdate()).exists())
