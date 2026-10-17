"""
super_admin/urls.py
-------------------
URL routes for the JewelDesk Super Admin Portal.
"""

from django.urls import path
from . import views

app_name = 'super_admin'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('showrooms/', views.showroom_list_view, name='showroom_list'),
    path('showrooms/<int:tenant_id>/', views.showroom_detail_view, name='showroom_detail'),
    path('showrooms/<int:tenant_id>/toggle-status/', views.toggle_tenant_status_view, name='toggle_tenant_status'),
    path('showrooms/<int:tenant_id>/impersonate/', views.impersonate_start_view, name='impersonate_start'),
    path('impersonate/exit/', views.impersonate_exit_view, name='impersonate_exit'),
    path('audit-logs/', views.audit_log_view, name='audit_logs'),
    path('subscriptions/', views.subscriptions_view, name='subscriptions'),
    path('settings/', views.settings_view, name='settings'),
]
