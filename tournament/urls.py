# tournament/urls.py
from django.urls import path
from . import views

app_name = 'tournament'

urlpatterns = [
    path('', views.tournament_list, name='list'),
    path('create/', views.create_tournament, name='create'),
    path('<int:tournament_id>/', views.tournament_detail, name='detail'),
    path('<int:tournament_id>/generate/', views.generate_matches, name='generate_matches'),
    path('<int:tournament_id>/bracket/', views.tournament_bracket_view, name='bracket'),
    path('<int:tournament_id>/standings/', views.round_robin_standings, name='standings'),
    path('<int:tournament_id>/delete/', views.delete_tournament, name='delete'),
    path('<int:tournament_id>/advance/', views.advance_to_next_round, name='advance_round'),
    path('<int:tournament_id>/round-status/', views.get_round_status, name='round_status'),
    path('match/<int:match_id>/update/', views.update_match, name='update_match'),
    path('api/match/<int:match_id>/update/', views.update_match_result, name='update_match_api'),
]