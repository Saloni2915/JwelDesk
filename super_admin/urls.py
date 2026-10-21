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
    
    # Demo meetings and lead management
    path('demos/', views.demo_list_view, name='demo_list'),
    path('demos/new/', views.demo_create_view, name='demo_create'),
    path('demos/<int:lead_id>/', views.demo_detail_view, name='demo_detail'),
    path('demos/<int:lead_id>/edit/', views.demo_edit_view, name='demo_edit'),
    path('demos/<int:lead_id>/action/', views.demo_action_view, name='demo_action'),
    path('demos/<int:lead_id>/convert/', views.demo_convert_view, name='demo_convert'),
    path('api/demo-request/', views.public_demo_request_view, name='public_demo_request'),

    # Platform support tickets
    path('tickets/', views.ticket_list_view, name='ticket_list'),
    path('tickets/new/', views.ticket_create_view, name='ticket_create'),
    path('tickets/<int:ticket_id>/', views.ticket_detail_view, name='ticket_detail'),
    path('tickets/<int:ticket_id>/update-status/', views.ticket_update_status_view, name='ticket_update_status'),

    # Reports & Analytics
    path('reports/', views.reports_view, name='reports'),
    path('reports/export/<str:report_type>/', views.reports_export_csv_view, name='reports_export_csv'),

    path('proposals/', views.proposal_list_view, name='proposal_list'),
    path('proposals/new/', views.proposal_create_view, name='proposal_create'),
    path('proposals/<int:proposal_id>/', views.proposal_detail_view, name='proposal_detail'),
    path('proposals/<int:proposal_id>/status/', views.proposal_status_update_view, name='proposal_status_update'),
    path('proposals/<int:proposal_id>/pdf/', views.proposal_download_pdf_view, name='proposal_download_pdf'),
    path('proposals/share/<str:token>/', views.proposal_client_view, name='proposal_client_view'),
    path('proposals/share/<str:token>/pdf/', views.proposal_client_download_pdf_view, name='proposal_client_download_pdf'),
    path('settings/', views.settings_view, name='settings'),
]
