# teams/forms.py
from django import forms
from .models import Team, TeamMember
from players.models import Player

class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter team name'
            })
        }

class AddTeamMemberForm(forms.Form):
    player = forms.ModelChoiceField(
        queryset=Player.objects.all().order_by('name'),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Select Player"
    )