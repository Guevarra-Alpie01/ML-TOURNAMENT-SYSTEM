# players/forms.py
from django import forms
from .models import Player, Rank, Role

class PlayerForm(forms.ModelForm):
    # Custom field for multiple role selection
    secondary_roles = forms.MultipleChoiceField(
        choices=Role.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Secondary Roles (Select all that apply)"
    )
    
    class Meta:
        model = Player
        fields = ['name', 'primary_role', 'secondary_roles', 'current_rank', 'highest_rank']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter player name'
            }),
            'primary_role': forms.Select(attrs={
                'class': 'form-control'
            }),
            'current_rank': forms.Select(attrs={
                'class': 'form-control'
            }),
            'highest_rank': forms.Select(attrs={
                'class': 'form-control'
            }),
        }
        labels = {
            'name': 'Player Name',
            'primary_role': 'Primary Role',
            'current_rank': 'Current Rank',
            'highest_rank': 'Highest Rank Reached',
        }
    
    def clean_secondary_roles(self):
        """Convert the list of roles to a comma-separated string"""
        roles = self.cleaned_data.get('secondary_roles', [])
        return ', '.join(roles) if roles else ''
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Save secondary roles as comma-separated string
        secondary_roles = self.cleaned_data.get('secondary_roles', [])
        instance.secondary_roles = ', '.join(secondary_roles) if secondary_roles else ''
        
        if commit:
            instance.save()
        return instance