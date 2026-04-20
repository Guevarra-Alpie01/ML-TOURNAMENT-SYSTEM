# players/forms.py
from django import forms
from .models import Player, Rank, Role

class PlayerForm(forms.ModelForm):
    # Single secondary role selection
    secondary_roles = forms.ChoiceField(
        choices=[('', '-- Select a role --')] + list(Role.choices),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        label="Secondary Role"
    )
    
    class Meta:
        model = Player
        fields = ['name', 'primary_role', 'secondary_roles', 'highest_rank']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter player name'
            }),
            'primary_role': forms.Select(attrs={
                'class': 'form-control'
            }),
            'highest_rank': forms.Select(attrs={
                'class': 'form-control'
            }),
        }
        labels = {
            'name': 'Player Name',
            'primary_role': 'Primary Role',
            'highest_rank': 'Highest Rank Reached',
        }
    
    def clean_secondary_roles(self):
        """Get the selected single role"""
        role = self.cleaned_data.get('secondary_roles', '')
        return role if role else ''
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Save single secondary role (not as comma-separated string)
        secondary_role = self.cleaned_data.get('secondary_roles', '')
        instance.secondary_roles = secondary_role if secondary_role else ''
        
        if commit:
            instance.save()
        return instance