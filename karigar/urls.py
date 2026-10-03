from django.urls import path
from . import views

app_name = 'karigar'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Karigar Master
    path('karigars/', views.karigar_list, name='karigar_list'),
    path('karigars/add/', views.karigar_create, name='karigar_create'),
    path('karigars/<int:pk>/', views.karigar_detail, name='karigar_detail'),
    path('karigars/<int:pk>/edit/', views.karigar_edit, name='karigar_edit'),
    path('karigars/<int:pk>/toggle-status/', views.karigar_toggle_status, name='karigar_toggle_status'),

    # Work Assignments
    path('assignments/', views.assignment_list, name='assignment_list'),
    path('assignments/pending/', views.pending_assignments, name='pending_assignments'),
    path('assignments/add/', views.assignment_create, name='assignment_create'),
    path('assignments/<int:pk>/', views.assignment_detail, name='assignment_detail'),
    path('assignments/<int:pk>/edit/', views.assignment_edit, name='assignment_edit'),
    path('assignments/<int:pk>/status/', views.assignment_status_update, name='assignment_status_update'),
    path('assignments/<int:pk>/receive/', views.assignment_receive, name='assignment_receive'),

    # Settlements / Payments
    path('settlements/', views.settlement_list, name='settlement_list'),
    path('settlements/add/', views.settlement_create, name='settlement_create'),
    path('settlements/<int:pk>/', views.settlement_detail, name='settlement_detail'),
    path('settlements/<int:pk>/cancel/', views.settlement_cancel, name='settlement_cancel'),

    # Reports
    path('reports/', views.reports, name='reports'),
]
