from django.urls import path
from . import views

app_name = 'wholesale'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Retailers / Parties
    path('parties/', views.party_list, name='party_list'),
    path('parties/add/', views.party_create, name='party_create'),
    path('parties/<int:pk>/', views.party_detail, name='party_detail'),
    path('parties/<int:pk>/edit/', views.party_edit, name='party_edit'),
    path('parties/<int:party_pk>/ledger/csv/', views.export_retailer_ledger_csv, name='party_ledger_csv'),

    # Wholesale Orders
    path('orders/', views.order_list, name='order_list'),
    path('orders/add/', views.order_create, name='order_create'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/status/', views.order_status_update, name='order_status_update'),
    path('orders/<int:pk>/delete/', views.order_delete, name='order_delete'),
    path('orders/<int:order_pk>/dispatch/', views.dispatch_create, name='dispatch_create'),
    path('orders/<int:order_pk>/invoice/', views.invoice_create_from_order, name='invoice_create_from_order'),

    # Dispatches
    path('dispatches/', views.dispatch_list, name='dispatch_list'),
    path('dispatches/<int:pk>/', views.dispatch_detail, name='dispatch_detail'),

    # Invoices & Billing
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf_view, name='invoice_pdf'),

    # Payments & Ledger
    path('payments/', views.payment_list, name='payment_list'),
    path('payments/add/', views.payment_create, name='payment_create'),
    path('ledger/', views.ledger_view, name='ledger_view'),

    # Returns & Credit Notes
    path('returns/', views.return_list, name='return_list'),
    path('returns/add/', views.return_create, name='return_create'),
    path('returns/<int:pk>/', views.return_detail, name='return_detail'),
    path('returns/<int:pk>/approve/', views.return_approve, name='return_approve'),
    path('returns/<int:pk>/restock/<int:item_pk>/', views.return_restock, name='return_restock'),
    path('returns/<int:pk>/credit-note/', views.return_issue_credit, name='return_issue_credit'),

    # Pricing & Catalogue
    path('pricing-rules/', views.pricing_rule_list, name='pricing_rules'),
    path('pricing-rules/add/', views.pricing_rule_create, name='pricing_rule_create'),
    path('catalogue/', views.catalogue_view, name='catalogue'),

    # Reports
    path('reports/', views.reports_dashboard, name='reports'),
]
