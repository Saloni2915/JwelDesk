"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from accounts.views import (
    login_view,
    signup_view,
    password_reset_view,
    password_reset_done_view,
    password_reset_confirm_view,
    password_reset_complete_view,
)
from .pwa_views import (
    manifest_view,
    service_worker_view,
    app_version_view,
    offline_view,
    download_report_view,
    view_report_view,
    download_brochure_view,
    view_brochure_view,
    digital_brochure_view,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('download-brochure/', download_brochure_view, name='download_brochure'),
    path('view-brochure/', view_brochure_view, name='view_brochure'),
    path('brochure/', digital_brochure_view, name='digital_brochure'),
    path('download-report/', download_report_view, name='download_project_report'),
    path('view-report/', view_report_view, name='view_project_report'),
    path('', include('inventory.urls')),
    path('accounts/', include('accounts.urls')),
    path('customers/', include('customers.urls')),
    path('custom-orders/', include('custom_orders.urls')),
    path('', include('sales.urls')),
    path('team/', include('team.urls')),
    path('karigar/', include('karigar.urls')),

    # Direct URL aliases for compatibility with Django auth defaults
    path('signup/', signup_view, name='signup_root'),
    path('accounts/signup/', signup_view, name='signup'),
    path('accounts/password-reset/', password_reset_view, name='password_reset'),
    path('accounts/password-reset/done/', password_reset_done_view, name='password_reset_done'),
    path('accounts/password-reset/confirm/<uidb64>/<token>/', password_reset_confirm_view, name='password_reset_confirm'),
    path('accounts/password-reset/complete/', password_reset_complete_view, name='password_reset_complete'),

    # Progressive Web App (PWA) endpoints
    path('manifest.json', manifest_view, name='pwa_manifest'),
    path('sw.js', service_worker_view, name='pwa_service_worker'),
    path('offline/', offline_view, name='pwa_offline'),
    path('api/app-version/', app_version_view, name='pwa_app_version'),
]



if settings.DEBUG:
    # Serve uploaded media files in development only.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
