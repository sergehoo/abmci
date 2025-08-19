from allauth.account.forms import SignupForm, LoginForm
from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.forms import ModelForm
from django.utils import timezone
from django.utils.crypto import get_random_string
from django_select2.forms import Select2Widget, Select2MultipleWidget
from django_countries import countries

from eden.models import Fiancailles, Mariage
from fidele.models import Fidele, Fonction, OuvrierPermanence, Permanence, BAPTEME_CHOICES, SEXE_CHOICES, \
    MARITAL_CHOICES, MembreType, Location, Department, Eglise

from event.models import Evenement


class FideleSignupForm(SignupForm):
    email = forms.EmailField(label="Adresse mail", required=True,
                             widget=forms.EmailInput(attrs={'class': 'form-control'}))
    first_name = forms.CharField(label="Nom", required=True, max_length=50,
                                 widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(label="Prénom", required=True, max_length=150,
                                widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(label="Téléphone", max_length=20, widget=forms.TextInput(attrs={'class': 'form-control'}))
    birthdate = forms.DateField(label="Date de naissance", required=True,
                                widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    eglise = forms.ModelChoiceField(label="Église d'enregistrement", queryset=Eglise.objects.all(), required=True,
                                    widget=forms.Select(attrs={'class': 'form-control'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs['class'] = 'form-control form-control-lg'
        self.fields['password2'].widget.attrs['class'] = 'form-control form-control-lg'

    #     self.fields['email'].widget.attrs['class'] = 'form-control form-control-lg'
    #     self.fields['phone'].widget.attrs['class'] = 'form-control form-control-lg'
    #     self.fields['first_name'].widget.attrs['class'] = 'form-control form-control-lg'
    #     self.fields['last_name'].widget.attrs['class'] = 'form-control form-control-lg'
    #     self.fields['birthdate'].widget.attrs['class'] = 'form-control form-control-lg'

    def save(self, request):
        # Sauvegarde de l'utilisateur
        user = super().save(request)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.save()

        # Création automatique du fidèle
        if not hasattr(user, 'fidele'):
            Fidele.objects.create(
                user=user,
                phone=self.cleaned_data.get('phone'),
                birthdate=self.cleaned_data.get('birthdate'),
                eglise=self.cleaned_data.get('eglise'),  # ✅ l’église sélectionnée
                qlook_id=get_random_string(12),
                date_entree=timezone.now().date(),
            )
        return user


class FideleLoginForm(LoginForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['login'].widget.attrs['class'] = 'form-control form-control-lg'
        self.fields['password'].widget.attrs['class'] = 'form-control form-control-lg'


class PermanenceForm(forms.ModelForm):
    class Meta:
        model = OuvrierPermanence
        fields = ['ouvrier', 'poste', 'position', 'activites', 'date', 'programme']
        exclude = ['programme']

    event = forms.ModelChoiceField(required=True, queryset=Evenement.objects.all(), empty_label='Aucun evenement',
                                   widget=forms.Select(attrs={'class': 'form-control', }))
    ouvrier = forms.ModelChoiceField(required=True, queryset=Fidele.objects.all(), empty_label='Aucun ouvrier',
                                     widget=forms.Select(
                                         attrs={'class': 'form-select form-select-sm', 'data-search': 'on'}))
    poste = forms.ModelChoiceField(required=True, queryset=Fonction.objects.all(), empty_label='Aucun poste',
                                   widget=forms.Select(attrs={'class': 'form-control', }))

    position = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    activites = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    date = forms.DateTimeField(required=False, widget=forms.DateTimeInput(attrs={'class': 'form-control date-picker'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ouvrier'].widget.attrs['class'] = 'form-control form-control-lg'
        self.fields['poste'].widget.attrs['class'] = 'form-control form-control-lg'
        # Ajoutez des choix pour le champ event basés sur les instances de Permanence
        # self.fields['event'].queryset = Evenement.objects.all()

    # def clean(self):
    #     cleaned_data = super().clean()
    #     ouvrier = cleaned_data.get('ouvrier')
    #     event = cleaned_data.get('programme.event')
    #
    #     if ouvrier and event:
    #         # Vérifiez si un ouvrier est déjà enregistré pour le même événement
    #         existing_permanence = OuvrierPermanence.objects.filter(
    #             ouvrier=ouvrier,
    #             event=event
    #         ).exclude(pk=self.instance.pk)  # Exclure l'enregistrement actuel lors de la modification
    #
    #         if existing_permanence.exists():
    #             raise ValidationError('This worker is already registered for the same event on the same date.')
    #
    #     return cleaned_data


class FideleUpdateForm(ModelForm):
    first_name = forms.CharField(required=False, max_length=100,
                                 widget=forms.TextInput(attrs={'class': 'form-control', }))
    last_name = forms.CharField(required=False, max_length=100,
                                widget=forms.TextInput(attrs={'class': 'form-control', }))

    birthdate = forms.DateField(required=False,
                                widget=forms.DateInput(
                                    attrs={'class': 'form-control date-picker', 'data-date-format': 'dd/mm/yyyy'}))
    sexe = forms.ChoiceField(required=False, choices=SEXE_CHOICES,
                             widget=forms.Select(attrs={'class': 'form-control', }))
    situation_matrimoniale = forms.ChoiceField(required=False, choices=MARITAL_CHOICES,
                                               widget=forms.Select(attrs={'class': 'form-control', }))
    nbr_enfants = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control', }))

    # membre = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control', }))

    phone = forms.CharField(required=False, max_length=100,
                            widget=forms.TextInput(attrs={'class': 'form-control', }))

    nationalite = forms.CharField(required=False, max_length=100,
                                  widget=forms.TextInput(attrs={'class': 'form-control', }))

    personal_mail = forms.CharField(required=False, max_length=100,
                                    widget=forms.TextInput(attrs={'class': 'form-control', }))

    date_entree = forms.DateField(required=False, widget=forms.DateInput(
        attrs={'class': 'form-control date-picker', 'data-date-format': 'dd/mm/yyyy'}))

    date_bapteme = forms.DateField(required=False,
                                   widget=forms.DateInput(
                                       attrs={'class': 'form-control date-picker', 'data-date-format': 'dd/mm/yyyy'}))

    eglise_origine = forms.CharField(required=False, max_length=100,
                                     widget=forms.TextInput(attrs={'class': 'form-control', }))

    type_bapteme = forms.ChoiceField(required=False, choices=BAPTEME_CHOICES,
                                     widget=forms.Select(attrs={'class': 'form-control', }))
    lieu_bapteme = forms.CharField(required=False, max_length=100,
                                   widget=forms.TextInput(attrs={'class': 'form-control', }))
    profession = forms.CharField(required=False, max_length=100,
                                 widget=forms.TextInput(attrs={'class': 'form-control', }))
    entreprise = forms.CharField(required=False, max_length=100,
                                 widget=forms.TextInput(attrs={'class': 'form-control', }))
    mensual_revenue = forms.DecimalField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control', }))
    salary_currency = forms.CharField(required=False, max_length=100,
                                      widget=forms.TextInput(attrs={'class': 'form-control', }))
    location = forms.ModelChoiceField(required=False, queryset=Location.objects.all(),
                                      widget=forms.Select(attrs={'class': 'form-control', }))

    departement = forms.ModelChoiceField(required=False, queryset=Department.objects.all(),
                                         widget=forms.Select(attrs={'class': 'form-control', }))
    fonction = forms.ModelChoiceField(required=False, queryset=Fonction.objects.all(),
                                      widget=forms.Select(attrs={'class': 'form-control', }))

    class Meta:
        model = Fidele
        fields = '__all__'
        exclude = (
            'created_at', 'user', 'is_deleted', 'photo', 'sortie', 'marie_a', 'frere', 'pere', 'mere', 'soeur',
            'enfant', 'type_membre', 'contry', 'signe', 'membre')

    def __init__(self, *args, **kwargs):
        super(FideleUpdateForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            self.fields['first_name'].initial = instance.user.first_name
            self.fields['last_name'].initial = instance.user.last_name

    def save(self, *args, **kwargs):
        # Enregistrer les modifications apportées aux champs first_name et last_name de l'utilisateur
        self.instance.user.first_name = self.cleaned_data['first_name']
        self.instance.user.last_name = self.cleaned_data['last_name']
        self.instance.user.save()

        # Continuer avec l'enregistrement du reste du formulaire
        return super(FideleUpdateForm, self).save(*args, **kwargs)


class UpdatePhotoForm(forms.ModelForm):
    photo = forms.ImageField(widget=forms.FileInput(attrs={'class': 'form-control-file'}))

    class Meta:
        model = Fidele
        fields = ('photo',)


class FideleTransferForm(forms.Form):
    nouvelle_eglise = forms.ModelChoiceField(
        queryset=Eglise.objects.all(),
        label="Nouvelle église",
        required=True
    )
    motif = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        label="Motif du transfert",
        required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nouvelle_eglise'].widget.attrs.update({'class': 'form-control'})
        self.fields['motif'].widget.attrs.update({'class': 'form-control'})


class ProfileCompletionForm(forms.ModelForm):
    class Meta:
        model = Fidele
        fields = []  # Définis dynamiquement selon les étapes

    def __init__(self, *args, step=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.step = step

        # Champs par étapes
        step_fields = {
            1: {
                'title': 'Informations personnelles',
                'description': 'Aidez-nous à mieux vous connaître',
                'fields': [
                    ('birthdate', 'Date de naissance'),
                    ('sexe', 'Genre'),
                    ('situation_matrimoniale', 'Situation matrimoniale'),
                    ('nbr_enfants', 'Nombre d\'enfants'),
                    ('nationalite', 'Nationalité'),
                    ('contry', 'Pays de résidence')
                ]
            },
            2: {
                'title': 'Coordonnées',
                'description': 'Comment pouvons-nous vous contacter ?',
                'fields': [
                    ('phone', 'Téléphone'),
                    ('profession', 'Profession'),
                    ('entreprise', 'Entreprise'),
                    ('mensual_revenue', 'Revenu mensuel'),
                    ('salary_currency', 'Devise du revenu')
                ]
            },
            3: {
                'title': 'Vie spirituelle',
                'description': 'Votre parcours de foi',
                'fields': [
                    ('date_entree', 'Date d’entrée dans l’église'),
                    ('date_bapteme', 'Date de baptême'),
                    ('type_bapteme', 'Type de baptême'),
                    ('lieu_bapteme', 'Lieu du baptême'),
                    ('eglise_origine', 'Église d’origine')
                ]
            },
            4: {
                'title': 'Relations familiales',
                'description': 'Liens familiaux dans la communauté',
                'fields': [
                    ('marie_a', 'Marié(e) à un membre ?'),
                    ('pere', 'Père membre ?'),
                    ('mere', 'Mère membre ?'),
                    ('frere', 'Frères membres ?'),
                    ('soeur', 'Sœurs membres ?'),
                    ('famille_alliance', 'Famille d’alliance')
                ]
            },
            5: {
                'title': 'Engagement dans l’église',
                'description': 'Votre implication actuelle',
                'fields': [
                    ('type_membre', 'Type de membre'),
                    ('membre', 'Statut de membre'),
                    ('location', 'Localisation'),
                    ('departement', 'Département'),
                    ('fonction', 'Fonction'),
                    ('eglise', 'Église locale'),
                    ('photo', 'Photo de profil'),
                    ('signe', 'Signe distinctif')
                ]
            }
        }

        # Extraire données de l'étape courante
        current_step_data = step_fields.get(step, {})
        self.step_title = current_step_data.get('title', '')
        self.step_description = current_step_data.get('description', '')

        self._meta.fields = [field for field, _ in current_step_data.get('fields', [])]

        # Construire les champs
        for field_name, label in current_step_data.get('fields', []):
            model_field = self._meta.model._meta.get_field(field_name)
            self.fields[field_name] = self.build_field(model_field, label)

    def build_field(self, field, label):
        common_attrs = {
            'class': 'form-control',
            'placeholder': label,
            'aria-label': label
        }
        if field.name == "contry":  # Forcer les pays
            return forms.ChoiceField(
                label=label,
                choices=list(countries),
                widget=Select2Widget(attrs={'class': 'form-control'}),
                required=False
            )

        if isinstance(field, models.DateField):
            return forms.DateField(
                label=label,
                widget=forms.DateInput(attrs={**common_attrs, 'type': 'date'}),
                required=False
            )
        elif isinstance(field, models.ImageField):
            return forms.ImageField(
                label=label,
                widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
                required=False
            )
        elif field.choices:
            return forms.ChoiceField(
                label=label,
                choices=field.choices,
                widget=Select2Widget(attrs=common_attrs),
                required=False
            )
        elif isinstance(field, models.ForeignKey):
            return forms.ModelChoiceField(
                label=label,
                queryset=field.related_model.objects.all(),
                widget=Select2Widget(attrs={**common_attrs, 'class': 'form-control select2'}),
                required=False
            )
        elif isinstance(field, models.ManyToManyField):
            return forms.ModelMultipleChoiceField(
                label=label,
                queryset=field.related_model.objects.all(),
                widget=Select2MultipleWidget(attrs=common_attrs),
                required=False
            )
        elif isinstance(field, models.IntegerField):
            return forms.IntegerField(
                label=label,
                widget=forms.NumberInput(attrs=common_attrs),
                required=False
            )
        elif isinstance(field, models.DecimalField):
            return forms.DecimalField(
                label=label,
                widget=forms.NumberInput(attrs=common_attrs),
                required=False
            )
        elif isinstance(field, models.TextField):
            return forms.CharField(
                label=label,
                widget=forms.Textarea(attrs={**common_attrs, 'rows': 3}),
                required=False
            )
        else:
            return forms.CharField(
                label=label,
                widget=forms.TextInput(attrs=common_attrs),
                required=False
            )


class FiancaillesForm(forms.ModelForm):
    homme = forms.ModelChoiceField(
        queryset=Fidele.objects.all(),
        label="Fiancé (Homme)",
        widget=forms.Select(attrs={"class": "form-control"})
    )
    femme = forms.ModelChoiceField(
        queryset=Fidele.objects.all(),
        label="Fiancée (Femme)",
        widget=forms.Select(attrs={"class": "form-control"})
    )

    class Meta:
        model = Fiancailles
        fields = [
            "homme", "femme", "date_demande", "date_ceremonie", "lieu_ceremonie",
            "conseiller", "sessions_conseil", "sessions_terminees", "statut", "documents"
        ]
        widgets = {
            "date_demande": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "date_ceremonie": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "lieu_ceremonie": forms.TextInput(attrs={"class": "form-control"}),
            "conseiller": forms.Select(attrs={"class": "form-control"}),
            "sessions_conseil": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "sessions_terminees": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "statut": forms.Select(attrs={"class": "form-control"}),
            "documents": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned = super().clean()
        homme = cleaned.get("homme")
        femme = cleaned.get("femme")
        date_demande = cleaned.get("date_demande")
        date_ceremonie = cleaned.get("date_ceremonie")
        sc = cleaned.get("sessions_conseil") or 0
        st = cleaned.get("sessions_terminees") or 0

        if homme and femme and homme == femme:
            raise ValidationError("Le fiancé et la fiancée doivent être deux personnes différentes.")

        if date_demande and date_ceremonie and date_ceremonie < date_demande:
            raise ValidationError("La date de cérémonie ne peut pas être antérieure à la date de demande.")

        if st > sc:
            raise ValidationError("Le nombre de sessions terminées ne peut pas dépasser le nombre de sessions prévues.")

        if date_demande and date_demande > timezone.now().date():
            raise ValidationError("La date de demande ne peut pas être dans le futur.")

        return cleaned


class MariageForm(forms.ModelForm):
    couple = forms.ModelMultipleChoiceField(
        queryset=Fidele.objects.all(),
        label="Couple (sélectionne 2 personnes)",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "8"})
    )
    temoins = forms.ModelMultipleChoiceField(
        queryset=Fidele.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "8"})
    )

    class Meta:
        model = Mariage
        fields = [
            "couple", "date_mariage", "lieu_mariage", "officiant", "temoins",
            "numero_acte", "contrat_matrimonial", "photos", "notes"
        ]
        widgets = {
            "date_mariage": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "lieu_mariage": forms.TextInput(attrs={"class": "form-control"}),
            "officiant": forms.Select(attrs={"class": "form-control"}),
            "numero_acte": forms.TextInput(attrs={"class": "form-control"}),
            "contrat_matrimonial": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "photos": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def clean(self):
        cleaned = super().clean()
        couple = cleaned.get("couple")
        date_mariage = cleaned.get("date_mariage")

        if couple is None or len(couple) != 2:
            raise ValidationError("Le couple doit contenir exactement deux personnes.")

        if date_mariage and date_mariage > timezone.now().date() + timezone.timedelta(days=365 * 5):
            raise ValidationError("La date de mariage semble trop lointaine.")

        return cleaned

class ConfirmDeleteForm(forms.Form):
    confirm = forms.CharField(
        label="Tapez SUPPRIMER pour confirmer",
        help_text="Cette action est irréversible.",
    )

    def clean_confirm(self):
        value = (self.cleaned_data["confirm"] or "").strip().upper()
        if value != "SUPPRIMER":
            raise forms.ValidationError("Vous devez taper exactement SUPPRIMER.")
        return value