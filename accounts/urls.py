from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('company-settings/', views.company_settings, name='company_settings'),
    path('settings/menu/', views.menu_settings, name='menu_settings'),
    path('menu-settings/', views.menu_settings, name='menu_settings_alias'),
    path('settings/menu/toggle/', views.menu_toggle_api, name='menu_toggle_api'),
    path('settings/language/', views.set_language_view, name='set_language'),
    path('set-language/', views.set_language_view, name='set_language_alias'),
    path('settings/themes/', views.themes, name='themes'),
    path('themes/', views.themes, name='themes_alias'),

    # Password reset flow
    path('password-reset/', views.password_reset_view, name='password_reset'),
    path('password-reset/done/', views.password_reset_done_view, name='password_reset_done'),
    path('password-reset/confirm/<uidb64>/<token>/', views.password_reset_confirm_view, name='password_reset_confirm'),
    path('password-reset/complete/', views.password_reset_complete_view, name='password_reset_complete'),
]

