from django.urls import path
from . import views

urlpatterns = [
    # Sales routes
    path('sales/', views.sale_list, name='sale_list'),
    path('sales/add/', views.sale_add, name='sale_add'),
    path('sales/<int:pk>/', views.sale_detail, name='sale_detail'),
    path('sales/<int:pk>/invoice/pdf/', views.sale_invoice_pdf, name='sale_invoice_pdf'),
    path('sales/<int:pk>/payments/add/', views.payment_add, name='payment_add'),

    # Reports routes
    path('sales/report/', views.sales_report, name='sales_report'),

    # Enquiry routes
    path('enquiries/', views.enquiry_list, name='enquiry_list'),
    path('enquiries/add/', views.enquiry_add, name='enquiry_add'),
    path('enquiries/<int:pk>/', views.enquiry_detail, name='enquiry_detail'),
    path('enquiries/<int:pk>/edit/', views.enquiry_edit, name='enquiry_edit'),
    path('enquiries/<int:pk>/delete/', views.enquiry_delete, name='enquiry_delete'),

    # Old Gold Exchange & Buyback routes
    path('old-gold/', views.old_gold_list, name='old_gold_list'),
    path('old-gold/exchange/', views.old_gold_exchange_create, name='old_gold_exchange_create'),
    path('old-gold/buyback/', views.old_gold_buyback_create, name='old_gold_buyback_create'),
    path('old-gold/<int:pk>/', views.old_gold_detail, name='old_gold_detail'),
    path('old-gold/<int:pk>/cancel/', views.old_gold_cancel, name='old_gold_cancel'),
    path('old-gold/api/rate/', views.old_gold_rate_api, name='old_gold_rate_api'),
]


