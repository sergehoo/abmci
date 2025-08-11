from datetime import datetime
import random

from allauth.account.signals import user_signed_up
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail, EmailMessage
from django.db.models.signals import post_save, pre_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.template.loader import get_template
from fidele.models import Fidele
from django.dispatch import Signal

notify = Signal()


def qlook():
    qlook = ("QL" + str(random.randrange(0, 999999999, 1)) + "SAH")
    return qlook


@receiver(post_save, sender=User)
def create_fidele(sender, instance, created, **kwargs):
    if created:
        fidele = Fidele.objects.create(user=instance)

@receiver(user_signed_up)
def create_user_profile_completion(sender, request, user, **kwargs):
    from .models import Fidele, UserProfileCompletion

    # Créer le profil Fidele s’il n’existe pas
    fidele, created = Fidele.objects.get_or_create(user=user)

    # Créer ou récupérer l'objet de suivi
    UserProfileCompletion.objects.get_or_create(user=user)

    # Vérifier les champs requis (ex: birthdate, sexe, phone)
    incomplete = any([
        not fidele.birthdate,
        not fidele.phone,
        not fidele.sexe,
        # ajoute ici d'autres champs obligatoires
    ])

    if incomplete:
        # Marquer dans la session qu'on doit compléter le profil
        request.session['complete_profile_required'] = True
