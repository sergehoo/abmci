from django import forms

from formation.models import (
    Formation, FormationSession, FormationModule, FormationInscription,
)


class FormationForm(forms.ModelForm):
    class Meta:
        model = Formation
        fields = ['nom', 'theme', 'description', 'duree_mois', 'format',
                  'formateur_principal', 'actif']


class FormationSessionForm(forms.ModelForm):
    class Meta:
        model = FormationSession
        fields = ['formation', 'nom', 'date_debut', 'date_fin', 'lieu',
                  'capacite_max', 'statut', 'formateur', 'notes']
        widgets = {
            'date_debut': forms.DateInput(attrs={'type': 'date'}),
            'date_fin':   forms.DateInput(attrs={'type': 'date'}),
            'notes':      forms.Textarea(attrs={'rows': 3}),
        }


class FormationModuleForm(forms.ModelForm):
    class Meta:
        model = FormationModule
        fields = ['ordre', 'titre', 'description', 'date_seance', 'duree_minutes']
        widgets = {
            'date_seance': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class FormationInscriptionForm(forms.ModelForm):
    class Meta:
        model = FormationInscription
        fields = ['fidele', 'commentaire']
        widgets = {
            'commentaire': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session
        # Restreint le queryset des fidèles à ceux qui ne sont pas déjà inscrits
        if session:
            already = session.inscriptions.values_list('fidele_id', flat=True)
            from fidele.models import Fidele
            qs = Fidele.objects.exclude(id__in=already).select_related('user')
            self.fields['fidele'].queryset = qs
