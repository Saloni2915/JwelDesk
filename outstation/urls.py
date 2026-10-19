"""
outstation/urls.py
------------------
URL routing for Outstation Jewellery Sales & Stock Tracking.
"""

from django.urls import path
from . import views

app_name = 'outstation'

urlpatterns = [
    # Dashboard & List
    path('', views.trip_list, name='trip_list'),
    path('trips/', views.trip_list, name='trip_list_alt'),

    # Trip Creation & Management
    path('trips/new/', views.trip_create, name='trip_create'),
    path('trips/<int:pk>/', views.trip_detail, name='trip_detail'),
    path('trips/<int:pk>/edit/', views.trip_edit, name='trip_edit'),

    # Stock Issuance
    path('trips/<int:pk>/issue-stock/', views.trip_issue_stock, name='trip_issue_stock'),

    # Record On-Trip Sale (B2B / B2C)
    path('trips/<int:pk>/sales/new/<int:item_id>/', views.trip_record_sale, name='trip_record_sale'),

    # Reconciliation & Discrepancies
    path('trips/<int:pk>/reconcile/<int:item_id>/', views.trip_reconcile_item, name='trip_reconcile_item'),
    path('trips/<int:pk>/resolve-discrepancy/<int:item_id>/', views.trip_resolve_discrepancy, name='trip_resolve_discrepancy'),

    # Final Trip Closure
    path('trips/<int:pk>/close/', views.trip_close, name='trip_close'),

    # Reports & Printing
    path('trips/<int:pk>/stock-sheet/', views.trip_stock_sheet, name='trip_stock_sheet'),
    path('trips/<int:pk>/export-csv/', views.trip_export_csv, name='trip_export_csv'),

    # =========================================================================
    # Exhibition Management Routes
    # =========================================================================
    path('exhibitions/', views.exhibition_list, name='exhibition_list'),
    path('exhibitions/new/', views.exhibition_create, name='exhibition_create'),
    path('exhibitions/<int:pk>/', views.exhibition_detail, name='exhibition_detail'),
    path('exhibitions/<int:pk>/edit/', views.exhibition_edit, name='exhibition_edit'),

    # Exhibition Stock Issuance
    path('exhibitions/<int:pk>/issue-stock/', views.exhibition_issue_stock, name='exhibition_issue_stock'),

    # Exhibition Sales (B2B & B2C)
    path('exhibitions/<int:pk>/sales/new/<int:item_id>/', views.exhibition_record_sale, name='exhibition_record_sale'),

    # Exhibition Expenses
    path('exhibitions/<int:pk>/expenses/add/', views.exhibition_record_expense, name='exhibition_record_expense'),
    path('exhibitions/<int:pk>/expenses/<int:expense_id>/delete/', views.exhibition_delete_expense, name='exhibition_delete_expense'),

    # Exhibition Stock Reconciliation & Discrepancies
    path('exhibitions/<int:pk>/reconcile/<int:item_id>/', views.exhibition_reconcile_item, name='exhibition_reconcile_item'),
    path('exhibitions/<int:pk>/resolve-discrepancy/<int:item_id>/', views.exhibition_resolve_discrepancy, name='exhibition_resolve_discrepancy'),

    # Exhibition Final Closure
    path('exhibitions/<int:pk>/close/', views.exhibition_close, name='exhibition_close'),

    # Exhibition Print & Export
    path('exhibitions/<int:pk>/stock-sheet/', views.exhibition_stock_sheet, name='exhibition_stock_sheet'),
    path('exhibitions/<int:pk>/export-csv/', views.exhibition_export_csv, name='exhibition_export_csv'),
]
