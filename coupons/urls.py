"""
coupons/urls.py
---------------
URL routing for JewelDesk multi-tenant customer coupon and promotion module.
"""

from django.urls import path
from . import views

app_name = 'coupons'

urlpatterns = [
    # Campaign Management
    path('', views.coupon_list, name='coupon_list'),
    path('create/', views.coupon_create, name='coupon_create'),
    path('<int:pk>/', views.coupon_detail, name='coupon_detail'),
    path('<int:pk>/edit/', views.coupon_edit, name='coupon_edit'),
    path('<int:pk>/duplicate/', views.coupon_duplicate, name='coupon_duplicate'),
    path('<int:pk>/status/', views.coupon_toggle_status, name='coupon_toggle_status'),

    # Batch Generation & Printing
    path('<int:pk>/batch/', views.coupon_generate_batch, name='coupon_generate_batch'),
    path('<int:pk>/print/', views.coupon_print, name='coupon_print'),

    # APIs & Sandbox
    path('preview-api/', views.coupon_preview_api, name='coupon_preview_api'),
    path('api/validate/', views.coupon_validate_api, name='coupon_validate_api'),
    path('clone-platform/', views.coupon_clone_platform, name='coupon_clone_platform'),

    # Reports & Analytics
    path('reports/', views.coupon_reports, name='coupon_reports'),
    path('reports/export/', views.coupon_reports_export, name='coupon_reports_export'),
]
