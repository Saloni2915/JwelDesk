from django.urls import path
from . import views

app_name = 'custom_orders'

urlpatterns = [
    path('', views.custom_order_list, name='custom_order_list'),
    path('add/', views.custom_order_add, name='custom_order_add'),
    path('<int:pk>/', views.custom_order_detail, name='custom_order_detail'),
    path('<int:pk>/edit/', views.custom_order_edit, name='custom_order_edit'),
    path('<int:pk>/delete/', views.custom_order_delete, name='custom_order_delete'),
    path('<int:pk>/status/', views.custom_order_status, name='custom_order_status'),
]
