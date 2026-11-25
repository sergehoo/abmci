"""Contrats d'API attendus par l'app Flutter Alliance Connect (lot 1 : session, appareils, choix, événements)."""
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from abmci.factories import fidele_of, make_eglise, make_user
from event.models import Evenement
from fidele.models import Department, Device

User = get_user_model()
MEDIA_TMP = tempfile.mkdtemp(prefix="abmci-test-media-contrats-")


class SessionTests(TestCase):
    def test_login_renvoie_un_refresh_utilisable(self):
        make_user("session", email="session@example.com")
        client = APIClient()
        r = client.post("/api/auth/login/", {"email": "session@example.com", "password": "Motdepasse-test-1"},
                        format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["access"])
        refresh = r.json()["refresh"]
        self.assertTrue(refresh)  # vide auparavant (JWT_AUTH_HTTPONLY) → session perdue après 60 min
        r = client.post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["access"])


class DeviceTests(TestCase):
    def test_enregistrement_idempotent_et_reattribution(self):
        a, b = make_user("tel_a"), make_user("tel_b")
        client = APIClient()
        client.force_authenticate(a)
        r = client.post("/api/devices/", {"token": "fcm-123", "platform": "android"}, format="json")
        self.assertEqual(r.status_code, 201)
        r = client.post("/api/devices/", {"token": "fcm-123", "platform": "android"}, format="json")
        self.assertEqual(r.status_code, 200)  # 400 auparavant
        client.force_authenticate(b)
        client.post("/api/devices/", {"token": "fcm-123", "platform": "ios"}, format="json")
        self.assertEqual(Device.objects.get(token="fcm-123").user, b)


class ChoicesTests(TestCase):
    def setUp(self):
        self.eglise = make_eglise("Cocody")
        self.user = make_user("choix")
        f = fidele_of(self.user)
        f.eglise = self.eglise
        f.save()
        # Recharger : le signal create_fidele laisse en cache une fiche sans église sur l'objet user
        self.user = User.objects.get(pk=self.user.pk)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_liste_et_detail(self):
        dep = Department.objects.create(name="Chorale")
        r = self.client.get("/api/choices/departements/?q=chor")
        self.assertEqual(r.json(), [{"id": dep.pk, "label": "Chorale"}])
        r = self.client.get(f"/api/choices/departements/{dep.pk}/")
        self.assertEqual(r.json()["label"], "Chorale")
        self.assertEqual(self.client.get("/api/choices/inconnu/").status_code, 404)

    def test_fideles_limites_a_l_eglise_et_a_la_recherche(self):
        voisin = make_user("voisin")
        voisin.first_name = "Koffi"
        voisin.save()
        fv = fidele_of(voisin)
        fv.eglise = self.eglise
        fv.save()
        autre = make_user("lointain")
        autre.first_name = "Koffi"
        autre.save()  # pas dans la même église
        self.assertEqual(self.client.get("/api/choices/fideles/").json(), [])
        ids = [c["id"] for c in self.client.get("/api/choices/fideles/?q=koffi").json()]
        self.assertEqual(ids, [fv.pk])

    def test_recherche_utilisateurs_sans_email(self):
        cible = make_user("aminata")
        r = self.client.get("/api/users/search/?q=amin")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [{"id": cible.pk, "name": "aminata", "avatar": None}])
        self.assertEqual(self.client.get("/api/users/search/?q=a").json(), [])


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class EventsContractTests(TestCase):
    def test_a_venir_passes_tous(self):
        eglise = make_eglise()
        user = make_user("evt")
        f = fidele_of(user)
        f.eglise = eglise
        f.save()
        now = timezone.now()
        futur = Evenement.objects.create(titre="Culte", lieu="T", description="d", eglise=eglise,
                                         date_debut=now + timedelta(days=2), date_fin=now + timedelta(days=2, hours=2))
        passe = Evenement.objects.create(titre="Veillée", lieu="T", description="d", eglise=eglise,
                                         date_debut=now - timedelta(days=3), date_fin=now - timedelta(days=3, hours=-2))
        client = APIClient()
        client.force_authenticate(User.objects.get(pk=user.pk))  # fiche fidèle à jour (église)
        ids = lambda url: [e["id"] for e in client.get(url).json()["results"]]
        self.assertEqual(ids("/api/events/upcoming/"), [futur.pk])
        self.assertEqual(ids("/api/events/past/"), [passe.pk])
        self.assertEqual(ids("/api/events/"), [futur.pk, passe.pk])

    def test_sans_eglise_liste_vide_et_pas_d_erreur_500(self):
        client = APIClient()
        client.force_authenticate(make_user("sans_eglise"))
        r = client.get("/api/events/upcoming/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"], [])


class ProfilTests(TestCase):
    def setUp(self):
        self.user = make_user("profil_api")
        self.client = APIClient()
        self.client.force_authenticate(User.objects.get(pk=self.user.pk))

    def test_lecture_avec_fiche_imbriquee(self):
        r = self.client.get("/api/user/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["fidele"]["id"], fidele_of(self.user).pk)

    def test_modification_json_et_champs_proteges(self):
        r = self.client.patch("/api/user/", {"first_name": "Awa", "email": "pirate@example.com",
                                             "fidele": {"profession": "Juriste", "membre": 1, "sexe": "Femme"}},
                              format="json")
        self.assertEqual(r.status_code, 200, r.content)
        f = fidele_of(self.user)
        self.assertEqual((f.profession, f.sexe, f.membre), ("Juriste", "Femme", 0))
        u = User.objects.get(pk=self.user.pk)
        self.assertEqual(u.first_name, "Awa")
        self.assertNotEqual(u.email, "pirate@example.com")

    def test_modification_multipart_avec_cles_pointees(self):
        r = self.client.patch("/api/user/", {"last_name": "Kone", "fidele.profession": "Médecin"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(fidele_of(self.user).profession, "Médecin")


class AnnuaireTests(TestCase):
    def test_limite_a_l_eglise_et_sans_coordonnees(self):
        eglise, autre = make_eglise("Cocody"), make_eglise("Abobo")
        moi, voisin, lointain = make_user("moi"), make_user("voisin_a"), make_user("lointain_a")
        for u, e in ((moi, eglise), (voisin, eglise), (lointain, autre)):
            f = fidele_of(u)
            f.eglise = e
            f.save()
        client = APIClient()
        client.force_authenticate(User.objects.get(pk=moi.pk))
        r = client.get("/api/annuaire/")
        self.assertEqual(r.status_code, 200)
        results = r.json()["results"]
        self.assertEqual({x["id"] for x in results}, {fidele_of(moi).pk, fidele_of(voisin).pk})
        self.assertFalse({"phone", "email", "birthdate"} & set(results[0]))
        self.assertEqual(client.get(f"/api/annuaire/{fidele_of(lointain).pk}/").status_code, 404)

    def test_sans_eglise_annuaire_vide(self):
        client = APIClient()
        client.force_authenticate(make_user("seul"))
        self.assertEqual(client.get("/api/annuaire/").json()["results"], [])


class FormationsApiTests(TestCase):
    def test_catalogue_detail_et_mes_inscriptions(self):
        from formation.models import Formation, FormationInscription, FormationSession
        user = make_user("eleve")
        formation = Formation.objects.create(nom="Préparation au mariage", theme="mariage")
        Formation.objects.create(nom="Archivée", actif=False)
        session = FormationSession.objects.create(formation=formation, nom="Promo 1",
                                                  date_debut=timezone.now().date())
        FormationInscription.objects.create(session=session, fidele=fidele_of(user))
        client = APIClient()
        client.force_authenticate(User.objects.get(pk=user.pk))
        liste = client.get("/api/formations/").json()
        self.assertEqual([f["nom"] for f in liste["results"]], ["Préparation au mariage"])
        detail = client.get(f"/api/formations/{formation.slug}/").json()
        self.assertEqual(detail["sessions"][0]["nom"], "Promo 1")
        mes = client.get("/api/formations/mes-inscriptions/").json()
        self.assertEqual(mes[0]["formation"], "Préparation au mariage")
