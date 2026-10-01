from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('inventory/', views.inventory_list, name='inventory_list'),
    path('inventory/add/', views.inventory_add, name='inventory_add'),
    path('inventory/<int:pk>/', views.inventory_detail, name='inventory_detail'),
    path('inventory/<int:pk>/edit/', views.inventory_edit, name='inventory_edit'),
    path('inventory/<int:pk>/delete/', views.inventory_delete, name='inventory_delete'),

    # Stock tracking routes
    path('inventory/<int:pk>/adjust-stock/', views.stock_adjust, name='stock_adjust'),
    path('inventory/stock-movements/', views.stock_movement_list, name='stock_movement_list'),

    # Bulk import routes
    path('inventory/import/', views.inventory_import, name='inventory_import'),
    path('inventory/import/sample-csv/', views.inventory_import_sample, name='inventory_import_sample'),

    # Metal price & Pricing Engine routes
    path('metal-prices/refresh/', views.metal_price_refresh, name='metal_price_refresh'),
    path('pricing/', views.pricing_calculator, name='pricing_calculator'),
    path('pricing/api/calculate/', views.api_calculate_price, name='api_calculate_price'),
    path('metal-rates/', views.metal_rates_view, name='metal_rates'),

    # Category routes
    path('inventory/categories/', views.category_list, name='category_list'),
    path('inventory/categories/add/', views.category_add, name='category_add'),
    path('inventory/categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('inventory/categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
]


