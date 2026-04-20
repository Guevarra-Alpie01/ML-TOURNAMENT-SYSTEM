# teams/urls.py
from django.urls import path
from . import views

app_name = 'teams'

urlpatterns = [
    path('team-list/', views.team_list, name='team_list'),
    path('create/', views.create_team_manual, name='create_team'),
    path('add-member/<int:team_id>/', views.add_team_member, name='add_member'),
    path('generate/', views.generate_balanced_teams_view, name='generate_teams'),
    path('<int:team_id>/', views.team_detail, name='team_detail'),
    path('delete/<int:team_id>/', views.delete_team, name='delete_team'),
    path('remove-member/<int:team_id>/<int:member_id>/', views.remove_member, name='remove_member'),
    path('waiting-list/', views.waiting_list_view, name='waiting_list'),
]