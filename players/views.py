# players/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Player
from .forms import PlayerForm


def home(request):
    return render(request, 'home.html')

def add_player(request):
    """Add a new player"""
    if request.method == 'POST':
        form = PlayerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Player added successfully!')
            return redirect('players:list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PlayerForm()
    
    return render(request, 'add_player.html', {'form': form})

def list_players(request):
    """List all players"""
    players = Player.objects.all()
    return render(request, 'list_players.html', {'players': players})

def edit_player(request, pk):
    """Edit player information"""
    player = get_object_or_404(Player, pk=pk)
    
    # Convert stored secondary roles back to list for the form
    initial_data = {
        'secondary_roles': player.get_secondary_roles_list()
    }
    
    if request.method == 'POST':
        form = PlayerForm(request.POST, instance=player)
        if form.is_valid():
            form.save()
            messages.success(request, 'Player updated successfully!')
            return redirect('players:list')
    else:
        form = PlayerForm(instance=player, initial=initial_data)
    
    return render(request, 'players/edit_player.html', {'form': form, 'player': player})

def delete_player(request, pk):
    """Delete a player"""
    player = get_object_or_404(Player, pk=pk)
    if request.method == 'POST':
        player.delete()
        messages.success(request, 'Player deleted successfully!')
        return redirect('players:list')
    return render(request, 'players/delete_player.html', {'player': player})

def player_detail(request, pk):
    """View player details"""
    player = get_object_or_404(Player, pk=pk)
    return render(request, 'players/player_detail.html', {'player': player})