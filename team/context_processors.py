"""
team/context_processors.py
--------------------------
Template context processor providing `user_perms` to templates for clean,
permission-aware rendering of sidebar, action buttons, and links.
"""

from .permissions import has_module_perm, is_admin_user


class ModulePermChecker:
    def __init__(self, checker, module):
        self.checker = checker
        self.module = module

    @property
    def can_view(self):
        return self.checker.has(self.module, 'view')

    @property
    def can_add(self):
        return self.checker.has(self.module, 'add')

    @property
    def can_edit(self):
        return self.checker.has(self.module, 'edit')

    @property
    def can_delete(self):
        return self.checker.has(self.module, 'delete')

    @property
    def can_export(self):
        return self.checker.has(self.module, 'export')

    def __bool__(self):
        """Allows `{% if user_perms.team %}` to check can_view."""
        return self.can_view


class UserPermsChecker:
    def __init__(self, user, tenant=None):
        self.user = user
        self.tenant = tenant
        self._cache = {}

    def has(self, module, action='view'):
        key = (module, action)
        if key not in self._cache:
            self._cache[key] = has_module_perm(self.user, module, action, tenant=self.tenant)
        return self._cache[key]

    @property
    def is_admin(self):
        if not hasattr(self, '_is_admin_cached'):
            self._is_admin_cached = is_admin_user(self.user, tenant=self.tenant)
        return self._is_admin_cached

    def __getattr__(self, module):
        return ModulePermChecker(self, module)


def team_permissions(request):
    """Context processor returning `user_perms` object scoped to request.tenant."""
    user = getattr(request, 'user', None)
    tenant = getattr(request, 'tenant', None)
    return {
        'user_perms': UserPermsChecker(user, tenant=tenant),
    }
