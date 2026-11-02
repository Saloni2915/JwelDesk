"""
purchases/urls.py
-----------------
URL routing for the Purchase Management Module.
"""
from django.urls import path
from . import views

app_name = 'purchases'

urlpatterns = [
    # Dashboard & Invoices
    path('', views.dashboard_view, name='dashboard'),
    path('invoices/', views.purchase_list_view, name='purchase_list'),
    path('invoices/new/', views.purchase_create_view, name='purchase_create'),
    path('invoices/<int:pk>/', views.purchase_detail_view, name='purchase_detail'),
    path('invoices/<int:pk>/edit/', views.purchase_edit_view, name='purchase_edit'),
    path('invoices/<int:pk>/confirm/', views.purchase_confirm_view, name='purchase_confirm'),
    path('invoices/<int:pk>/cancel/', views.purchase_cancel_view, name='purchase_cancel'),
    path('invoices/<int:pk>/print/', views.purchase_voucher_view, name='purchase_voucher'),

    # Suppliers / Parties
    path('suppliers/', views.supplier_list_view, name='supplier_list'),
    path('suppliers/new/', views.supplier_create_view, name='supplier_create'),
    path('suppliers/<int:pk>/', views.supplier_detail_view, name='supplier_detail'),
    path('suppliers/<int:pk>/edit/', views.supplier_edit_view, name='supplier_edit'),
    path('suppliers/<int:pk>/ledger/', views.supplier_ledger_view, name='supplier_ledger'),

    # Payments
    path('payments/', views.payment_list_view, name='payment_list'),
    path('payments/new/', views.payment_create_view, name='payment_create'),
    path('payments/<int:pk>/receipt/', views.payment_receipt_view, name='payment_receipt'),
    path('payments/<int:pk>/cancel/', views.payment_cancel_view, name='payment_cancel'),

    # Returns
    path('returns/', views.return_list_view, name='return_list'),
    path('returns/new/<int:invoice_id>/', views.return_create_view, name='return_create'),
    path('returns/<int:pk>/', views.return_detail_view, name='return_detail'),

    # Reports & Settings
    path('reports/', views.reports_view, name='reports'),
    path('reports/export/', views.reports_export_csv_view, name='reports_export'),
    path('settings/', views.settings_view, name='settings'),

    # AJAX APIs for calculations & supplier selection
    path('api/supplier/<int:pk>/', views.api_supplier_details, name='api_supplier_details'),
    path('api/rates/', views.api_current_metal_rates, name='api_metal_rates'),
]
