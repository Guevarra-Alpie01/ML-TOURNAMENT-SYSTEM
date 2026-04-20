# players/urls.py
from django.urls import path
from . import views

app_name = 'players'

urlpatterns = [
    path('list/', views.list_players, name='list'),
    path('add/', views.add_player, name='add'),
    path('edit/<int:pk>/', views.edit_player, name='edit'),
    path('delete/<int:pk>/', views.delete_player, name='delete'),
    path('detail/<int:pk>/', views.player_detail, name='detail'),
]