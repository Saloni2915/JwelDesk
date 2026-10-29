"""
team/middleware.py
------------------
Branch-based isolation, context resolution, and access security middleware for JewelDesk.

Resolves:
- `request.allowed_branches`: QuerySet of active Branch objects this user has authorization to access.
- `request.can_view_all_branches`: Boolean, True if user is authorized to view consolidated "All Branches".
- `request.branch`: The currently selected active Branch object, or None if "All Branches" is active or unauthenticated.
- `request.active_branch_id`: Branch ID or 'all'.
- `request.is_all_branches`: Boolean, True when "All Branches" consolidated mode is selected.
"""

import logging
from .models import Branch, Employee
from .permissions import is_admin_user

logger = logging.getLogger(__name__)


class BranchMiddleware:
    """Enforces branch resolution and authorization context per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        tenant = getattr(request, 'tenant', None)

        request.branch = None
        request.active_branch_id = None
        request.can_view_all_branches = False
        request.allowed_branches = Branch.objects.none()
        request.available_branches = []
        request.is_all_branches = False

        if user and user.is_authenticated and tenant:
            try:
                # 1. Determine user role & permissions
                is_admin = is_admin_user(user, tenant=tenant)
                can_view_all = is_admin or user.is_superuser or (tenant.owner_id == user.id)

                # 2. Check employee-assigned branches
                emp = getattr(user, '_cached_employee_profile', None)
                if emp is None and not getattr(user, '_checked_employee_profile', False):
                    try:
                        emp = user.employee_profile
                    except Exception:
                        emp = None
                    user._cached_employee_profile = emp
                    user._checked_employee_profile = True

                all_tenant_branches = Branch.objects.filter(tenant=tenant, is_active=True).order_by('-is_default', 'name')
                if not all_tenant_branches.exists():
                    # Ensure default branch exists
                    Branch.ensure_default_branch(tenant)
                    all_tenant_branches = Branch.objects.filter(tenant=tenant, is_active=True).order_by('-is_default', 'name')

                if is_admin or not emp:
                    allowed_branches = all_tenant_branches
                    can_view_all = True
                else:
                    emp_branches = emp.branches.filter(tenant=tenant, is_active=True).order_by('-is_default', 'name')
                    if emp_branches.exists():
                        allowed_branches = emp_branches
                        can_view_all = False
                    else:
                        # Employee with no specific branch restrictions can access all branches in tenant
                        allowed_branches = all_tenant_branches
                        can_view_all = is_admin

                request.allowed_branches = allowed_branches
                request.available_branches = list(allowed_branches)
                request.can_view_all_branches = can_view_all

                # 3. Resolve active branch from session
                session_key = f'active_branch_id_{tenant.id}'
                session_val = request.session.get(session_key)

                if session_val == 'all' and can_view_all:
                    request.branch = None
                    request.active_branch_id = 'all'
                    request.is_all_branches = True
                elif session_val:
                    try:
                        b_id = int(session_val)
                        matched = allowed_branches.filter(id=b_id).first()
                        if matched:
                            request.branch = matched
                            request.active_branch_id = matched.id
                            request.is_all_branches = False
                        else:
                            # Stale or unauthorized branch in session -> pick fallback
                            fallback = allowed_branches.filter(is_default=True).first() or allowed_branches.first()
                            request.branch = fallback
                            request.active_branch_id = fallback.id if fallback else None
                            request.is_all_branches = False
                            request.session[session_key] = request.active_branch_id
                    except (ValueError, TypeError):
                        fallback = allowed_branches.filter(is_default=True).first() or allowed_branches.first()
                        request.branch = fallback
                        request.active_branch_id = fallback.id if fallback else None
                        request.is_all_branches = False
                        request.session[session_key] = request.active_branch_id
                else:
                    # Initial load: default branch
                    fallback = allowed_branches.filter(is_default=True).first() or allowed_branches.first()
                    request.branch = fallback
                    request.active_branch_id = fallback.id if fallback else None
                    request.is_all_branches = False
                    request.session[session_key] = request.active_branch_id

            except Exception as e:
                logger.warning("BranchMiddleware resolution error: %s", e)

        response = self.get_response(request)
        return response
