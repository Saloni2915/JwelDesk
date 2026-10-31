"""
girvi/urls.py
-------------
URL routing for the Girvi (Jewellery Pledge & Loan Management) module.
"""

from django.urls import path
from . import views

app_name = 'girvi'

urlpatterns = [
    # Dashboard & Lists
    path('', views.girvi_dashboard, name='dashboard'),
    path('loans/', views.girvi_loan_list, name='loan_list'),
    path('loans/new/', views.girvi_loan_create, name='loan_create'),
    path('loans/<int:loan_id>/', views.girvi_loan_detail, name='loan_detail'),

    # Financial Actions
    path('loans/<int:loan_id>/payments/new/', views.girvi_payment_create, name='payment_create'),
    path('payments/<int:payment_id>/reverse/', views.girvi_payment_reverse, name='payment_reverse'),
    path('loans/<int:loan_id>/waivers/new/', views.girvi_waiver_create, name='waiver_create'),
    path('loans/<int:loan_id>/release/', views.girvi_collateral_release, name='collateral_release'),

    # Printable Documents
    path('loans/<int:loan_id>/print/', views.girvi_loan_print, name='loan_print'),
    path('payments/<int:payment_id>/receipt/', views.girvi_payment_receipt_print, name='payment_receipt_print'),
    path('loans/<int:loan_id>/release/receipt/', views.girvi_release_receipt_print, name='release_receipt_print'),

    # Configuration & Settings
    path('settings/', views.girvi_settings, name='settings'),

    # Quick Add Customer API
    path('api/customers/quick-add/', views.customer_quick_add, name='customer_quick_add'),
]
