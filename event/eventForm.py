from datetime import timedelta

from django import forms

from event.models import Evenement

class EvenementForm(forms.ModelForm):
    class Meta:
        model = Evenement
        fields = [
            'titre', 'date_debut', 'date_fin', 'lieu', 'description',
            'type', 'banner', 'is_recurrent', 'recurrence_rule', 'end_recurrence'
        ]
        widgets = {
            "titre": forms.TextInput(attrs={"class": "form-control"}),
            "date_debut": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "date_fin": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "lieu": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "type": forms.Select(attrs={"class": "form-control"}),
            "banner": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "is_recurrent": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "recurrence_rule": forms.TextInput(attrs={"class": "form-control"}),
            "end_recurrence": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_recurrent"):
            if not cleaned.get("recurrence_rule"):
                self.add_error("recurrence_rule", "La règle de récurrence est requise.")
            if not cleaned.get("end_recurrence"):
                cleaned["end_recurrence"] = cleaned["date_debut"] + timedelta(days=365)
            if cleaned["end_recurrence"] <= cleaned["date_debut"]:
                self.add_error("end_recurrence", "La fin de récurrence doit être postérieure au début.")
        return cleaned