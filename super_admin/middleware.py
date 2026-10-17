"""
super_admin/middleware.py
-------------------------
Impersonation context and security middleware for JewelDesk.
Maintains session-level impersonation state, prevents privilege escalation,
and restricts sensitive mutations while in customer impersonation mode.
"""

import logging
from django.core.exceptions import PermissionDenied
from django.urls import reverse

logger = logging.getLogger('super_admin.security')


class SuperAdminImpersonationMiddleware:
    """Enforces safety constraints during customer impersonation.

    Responsibilities:
    1. Annotates `request.is_impersonated` and impersonator metadata.
    2. Blocks impersonated sessions from accessing `/super-admin/` (except the exit action).
    3. Blocks impersonated sessions from accessing Django admin (`/admin/`).
    4. Guards against customer credential modification while impersonating.
    """

    RESTRICTED_MUTATION_PATHS = [
        '/accounts/password-change/',
        '/accounts/password-reset/',
        '/accounts/delete/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        impersonator_id = request.session.get('impersonator_id')

        if impersonator_id:
            request.is_impersonated = True
            request.impersonator_id = impersonator_id
            request.impersonator_username = request.session.get('impersonator_username', 'Platform Admin')
            request.impersonated_tenant_id = request.session.get('impersonated_tenant_id')
            request.impersonated_user_id = request.session.get('impersonated_user_id')

            path = request.path

            # Allow the exit action so admin can safely return
            exit_url = reverse('super_admin:impersonate_exit')
            if path.startswith('/super-admin/') and path != exit_url:
                logger.warning(
                    "Blocked impersonated access attempt to super admin URL: %s by user %s (impersonator %s)",
                    path,
                    getattr(request.user, 'username', 'anon'),
                    request.impersonator_username
                )
                raise PermissionDenied(
                    "Platform Admin portal access is restricted while impersonating a customer. "
                    "Please use 'Return to Super Admin' to exit impersonation mode."
                )

            # Block Django built-in admin access
            if path.startswith('/admin/'):
                logger.warning(
                    "Blocked impersonated access attempt to /admin/ by user %s",
                    getattr(request.user, 'username', 'anon')
                )
                raise PermissionDenied(
                    "Django Admin access is prohibited while in customer impersonation mode."
                )

            # Block sensitive credential modifications during impersonation
            if request.method == 'POST' and any(path.startswith(p) for p in self.RESTRICTED_MUTATION_PATHS):
                logger.warning(
                    "Blocked credential modification attempt during impersonation: %s", path
                )
                raise PermissionDenied(
                    "Modifying customer passwords, security settings, or deleting accounts "
                    "is strictly prohibited during support impersonation."
                )
        else:
            request.is_impersonated = False

        return self.get_response(request)
