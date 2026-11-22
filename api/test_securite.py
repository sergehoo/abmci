"""Tests ciblés des corrections de sécurité et des endpoints API réparés."""
import hashlib
import hmac
import json
import tempfile
from unittest import mock

from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from abmci.factories import fidele_of, make_user
from fidele.models import AccountDeletionRequest, BibleTag, Donation, DonationCategory, NotificationUser, \
    PrayerComment, PrayerRequest
from fidele.views import process_account_deletion_request

PAYSTACK_TEST_KEY = "sk_test_cle_de_test_unitaire"


def _signed(body: bytes, key=PAYSTACK_TEST_KEY):
    return hmac.new(key.encode(), body, hashlib.sha512).hexdigest()


@override_settings(PAYSTACK_SECRET_KEY=PAYSTACK_TEST_KEY)
class PaystackWebhookTests(TestCase):
    url = "/api/paystack/webhook/"

    def setUp(self):
        self.client = APIClient()
        cat = DonationCategory.objects.create(code="offrande", name="Offrande")
        self.donation = Donation.objects.create(category=cat, amount=5000, reference="DON-TEST", status="pending")

    def _post(self, payload, signature):
        body = json.dumps(payload).encode()
        headers = {"HTTP_X_PAYSTACK_SIGNATURE": signature} if signature is not None else {}
        return self.client.post(self.url, data=body, content_type="application/json", **headers)

    def _payload(self, amount=500000):
        return {"event": "charge.success", "data": {"reference": "DON-TEST", "status": "success", "amount": amount}}

    def test_sans_signature_refuse(self):
        r = self._post(self._payload(), None)
        self.assertEqual(r.status_code, 401)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, "pending")

    def test_signature_invalide_refusee(self):
        r = self._post(self._payload(), "0" * 128)
        self.assertEqual(r.status_code, 401)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, "pending")

    def test_signature_valide_marque_le_don_paye(self):
        payload = self._payload()
        r = self._post(payload, _signed(json.dumps(payload).encode()))
        self.assertEqual(r.status_code, 200)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, "success")
        self.assertIsNotNone(self.donation.paid_at)

    def test_montant_incoherent_ignore(self):
        payload = self._payload(amount=100)  # 1 XOF au lieu de 5000
        r = self._post(payload, _signed(json.dumps(payload).encode()))
        self.assertEqual(r.status_code, 200)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, "pending")

    @override_settings(PAYSTACK_SECRET_KEY="")
    def test_cle_absente_refuse_meme_signature_cle_vide(self):
        payload = self._payload()
        r = self._post(payload, _signed(json.dumps(payload).encode(), key=""))
        self.assertEqual(r.status_code, 401)


class DonationVerifyTests(TestCase):
    def test_reponse_paystack_brute_non_renvoyee(self):
        cat = DonationCategory.objects.create(code="dime", name="Dîme")
        Donation.objects.create(category=cat, amount=1000, reference="DON-V", status="pending")
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"status": True, "data": {"status": "pending", "customer": {"email": "x@y.z"}}}
        with mock.patch("api.views.ps_verify", return_value=fake):
            r = APIClient().get("/api/donations/verify/DON-V/")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("paystack", r.json())


class FidelesApiTests(TestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.staff = make_user("admin_eglise", staff=True)
        self.client = APIClient()

    def test_liste_limitee_a_sa_propre_fiche(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get("/api/fideles/")
        self.assertEqual(r.status_code, 200)
        ids = [f["id"] for f in r.json()["results"]]
        self.assertEqual(ids, [fidele_of(self.alice).pk])

    def test_staff_voit_tous_les_fideles(self):
        self.client.force_authenticate(self.staff)
        r = self.client.get("/api/fideles/")
        self.assertEqual(r.json()["count"], 3)

    def test_pas_d_acces_a_la_fiche_d_un_autre(self):
        self.client.force_authenticate(self.alice)
        bob_pk = fidele_of(self.bob).pk
        self.assertEqual(self.client.get(f"/api/fideles/{bob_pk}/").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/fideles/{bob_pk}/", {"profession": "x"}).status_code, 404)

    def test_champs_d_administration_non_modifiables(self):
        self.client.force_authenticate(self.alice)
        pk = fidele_of(self.alice).pk
        r = self.client.patch(f"/api/fideles/{pk}/", {"membre": 1, "is_deleted": 1, "firebase_uid": "pirate",
                                                       "profession": "Enseignante"}, format="json")
        self.assertEqual(r.status_code, 200)
        f = fidele_of(self.alice)
        self.assertEqual(f.profession, "Enseignante")
        self.assertEqual(f.membre, 0)
        self.assertEqual(f.is_deleted, 0)
        self.assertIsNone(f.firebase_uid)

    def test_creation_reservee_au_staff_et_fonctionnelle(self):
        data = {"email": "nouveau@example.com", "first_name": "Awa", "last_name": "Kone",
                "password": "Motdepasse-test-2", "profession": "Infirmière"}
        self.assertEqual(APIClient().post("/api/fideles/create/", data, format="json").status_code, 401)
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.post("/api/fideles/create/", data, format="json").status_code, 403)
        self.client.force_authenticate(self.staff)
        r = self.client.post("/api/fideles/create/", data, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        f = fidele_of(self.staff.__class__.objects.get(email="nouveau@example.com"))
        self.assertEqual(f.profession, "Infirmière")


class PasswordResetRedirectTests(TestCase):
    def test_parametres_malveillants_refuses(self):
        r = self.client.get('/api/auth/password/reset/confirm/x%22%3E%3Cscript%3E/abc-def/')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(b"<script>", r.content)

    def test_lien_valide_redirige(self):
        r = self.client.get("/api/auth/password/reset/confirm/MTI/c8x2k1-0123456789abcdef/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"uid=MTI&amp;token=c8x2k1-0123456789abcdef", r.content)


@mock.patch("fidele.signals.send_to_topic")
@mock.patch("abmci.services.notifications.send_to_user")
class PrieresTests(TestCase):
    def setUp(self):
        self.auteur = make_user("auteur")
        self.lecteur = make_user("lecteur")

    def _priere(self):
        return PrayerRequest.objects.create(user=self.auteur, title="Guérison", content="Merci de prier")

    def test_lecture_anonyme_refusee(self, *_):
        self._priere()
        self.assertEqual(APIClient().get("/api/prayer-requests/").status_code, 401)

    def test_email_de_l_auteur_masque(self, *_):
        self._priere()
        client = APIClient()
        client.force_authenticate(self.lecteur)
        r = client.get("/api/prayer-requests/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["user"]["email"], "")

    def test_upload_audio_limite_aux_fichiers_audio(self, *_):
        client = APIClient()
        client.force_authenticate(self.auteur)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            html = SimpleUploadedFile("note.html", b"<script>alert(1)</script>", content_type="text/html")
            r = client.post("/api/prayer-requests/", {"title": "t", "content": "c", "audio_note": html},
                            format="multipart")
            self.assertEqual(r.status_code, 400)
            self.assertIn("audio_note", r.json())
            audio = SimpleUploadedFile("enregistrement.m4a", b"\x00\x00\x00\x18ftypM4A ",
                                       content_type="application/octet-stream")
            r = client.post("/api/prayer-requests/", {"title": "t", "content": "c", "audio_note": audio},
                            format="multipart")
            self.assertEqual(r.status_code, 201, r.content)

    def test_commentaire_cree_sans_erreur_500(self, send_to_user, _topic):
        priere = self._priere()
        client = APIClient()
        client.force_authenticate(self.lecteur)
        with self.captureOnCommitCallbacks(execute=True):
            r = client.post("/api/prayer-comments/", {"prayer": priere.pk, "content": "Amen"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(PrayerComment.objects.filter(prayer=priere, user=self.lecteur).exists())
        # Notification in-app créée pour l'auteur de la prière
        self.assertTrue(NotificationUser.objects.filter(user=self.auteur, notification__type="COMMENT_NEW").exists())


@mock.patch("abmci.services.notifications.send_to_user")
class BibleTagTests(TestCase):
    def test_tag_cree_et_notifie_sans_erreur_500(self, send_to_user):
        sender, recipient = make_user("emetteur"), make_user("destinataire")
        client = APIClient()
        client.force_authenticate(sender)
        r = client.post("/api/bible/tags/", {"recipient": recipient.email, "version": "LSG", "book": "Jean",
                                             "chapter": 3, "verse": 16}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(BibleTag.objects.filter(recipient=recipient).exists())
        self.assertTrue(NotificationUser.objects.filter(user=recipient, notification__type="VERSE_TAG").exists())
        self.assertEqual(send_to_user.call_args.args[0].pk, recipient.pk)


class SuppressionCompteTests(TestCase):
    def test_demande_via_api_jwt(self):
        user = make_user("partant")
        client = APIClient()
        client.force_authenticate(user)
        r = client.post("/api/account/delete/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(AccountDeletionRequest.objects.filter(user=user, status="requested").exists())
        self.assertEqual(APIClient().post("/api/account/delete/").status_code, 401)

    def test_traitement_supprime_le_compte_et_garde_la_demande(self):
        user = make_user("a_supprimer")
        conjoint = make_user("conjoint")
        f = fidele_of(user)
        f.marie_a = fidele_of(conjoint)
        f.save()
        req = AccountDeletionRequest.objects.create(user=user)

        process_account_deletion_request(req.pk)

        req.refresh_from_db()
        self.assertEqual(req.status, "done")
        self.assertIsNone(req.user_id)
        self.assertFalse(user.__class__.objects.filter(pk=user.pk).exists())
        # Le conjoint n'est plus supprimé en cascade
        self.assertTrue(user.__class__.objects.filter(pk=conjoint.pk).exists())


class VerifyEmailTests(TestCase):
    def test_cle_valide_verifie_l_adresse(self):
        user = make_user("verif")
        address = EmailAddress.objects.create(user=user, email=user.email, verified=False, primary=True)
        key = EmailConfirmationHMAC(address).key
        r = self.client.get(f"/api/auth/verify-email/{key}/")
        self.assertEqual(r.status_code, 200)
        address.refresh_from_db()
        self.assertTrue(address.verified)

    def test_cle_invalide(self):
        self.assertEqual(self.client.get("/api/auth/verify-email/inconnue/").status_code, 400)


class AuthenticationConfigTests(TestCase):
    def test_basic_auth_desactivee(self):
        make_user("basic")
        import base64
        token = base64.b64encode(b"basic:Motdepasse-test-1").decode()
        r = self.client.get("/api/user/", HTTP_AUTHORIZATION=f"Basic {token}")
        self.assertEqual(r.status_code, 401)
