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
    path('subscriptions/<int:tenant_id>/update/', views.subscription_update_view, name='subscription_update'),
    path('subscriptions/<int:tenant_id>/record-payment/', views.subscription_record_payment_view, name='subscription_record_payment'),
    path('proposals/', views.proposal_list_view, name='proposal_list'),
    path('proposals/new/', views.proposal_create_view, name='proposal_create'),
    path('proposals/<int:proposal_id>/', views.proposal_detail_view, name='proposal_detail'),
    path('proposals/<int:proposal_id>/status/', views.proposal_status_update_view, name='proposal_status_update'),
    path('proposals/share/<str:token>/', views.proposal_client_view, name='proposal_client_view'),
    path('settings/', views.settings_view, name='settings'),
]
