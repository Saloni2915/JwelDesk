from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('company-settings/', views.company_settings, name='company_settings'),
    path('settings/themes/', views.themes, name='themes'),
]
