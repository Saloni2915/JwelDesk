"""
team/views.py
-------------
All views for the Team / Employee Management module.

Access control & Security:
  - Backend authorization enforced via `require_permission` and `has_module_perm`.
  - Manual URL access without permissions is rejected with HTTP 403 (PermissionDenied).
  - Normal employees cannot escalate their privileges, alter their own permissions,
    or assign the Admin role to anyone.
  - A user cannot deactivate their own account.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import (
    BranchForm,
    EmployeeCreateForm,
    EmployeeDocumentForm,
    EmployeeEditForm,
    EmployeeLinkAccountForm,
    EmployeePasswordResetForm,
    PermissionForm,
    RoleForm,
)
from .models import (
    Branch,
    Employee,
    EmployeeDocument,
    EmployeePermission,
    Role,
)
from .permissions import has_module_perm, is_admin_user, require_permission

User = get_user_model()


def _can_view_employee(request, employee):
    """Staff with team view perm OR the employee viewing their own profile."""
    if hasattr(request.user, 'employee_profile') and request.user.employee_profile and request.user.employee_profile.pk == employee.pk:
        return True
    return has_module_perm(request.user, 'team', 'view')


# ---------------------------------------------------------------------------
# Employee list
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'view')
def employee_list(request):
    """Show all employees with search and multi-facet filtering."""
    qs = Employee.objects.select_related('user', 'role').prefetch_related('branches')

    q = request.GET.get('q', '').strip()
    role_id = request.GET.get('role', '').strip()
    dept = request.GET.get('department', '').strip()
    status = request.GET.get('status', '').strip()
    branch_id = request.GET.get('branch', '').strip()

    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(full_name__icontains=q) |
            Q(employee_id__icontains=q) |
            Q(email__icontains=q) |
            Q(mobile__icontains=q) |
            Q(designation__icontains=q)
        )
    if role_id:
        qs = qs.filter(role_id=role_id)
    if dept:
        qs = qs.filter(department=dept)
    if status:
        qs = qs.filter(status=status)
    if branch_id:
        qs = qs.filter(branches__id=branch_id)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'team/employee_list.html', {
        'page_obj': page,
        'employees': page.object_list,
        'roles': Role.objects.all(),
        'departments': [c[0] for c in Employee.DEPT_CHOICES],
        'branches': Branch.objects.filter(is_active=True),
        'statuses': Employee.STATUS_CHOICES,
        'q': q,
        'sel_role': role_id,
        'sel_dept': dept,
        'sel_status': status,
        'sel_branch': branch_id,
        'total_count': qs.count(),
        'can_add_employee': has_module_perm(request.user, 'team', 'add'),
    })


# ---------------------------------------------------------------------------
# Employee create
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'add')
def employee_create(request):
    """Create a new employee, optionally creating or linking a Django User."""
    if not Role.objects.exists():
        Role.ensure_builtin_roles()

    if request.method == 'POST':
        form = EmployeeCreateForm(request.POST, request.FILES)
        if form.is_valid():
            # Privilege escalation guard: Only admins can assign the Admin role
            chosen_role = form.cleaned_data.get('role')
            if chosen_role and chosen_role.name == Role.ROLE_ADMIN and not is_admin_user(request.user):
                form.add_error('role', 'Only administrators can assign the Admin role.')
            else:
                employee = form.save(created_by=request.user)
                msg = f'Employee {employee.full_name} ({employee.employee_id}) created successfully.'
                if employee.user:
                    msg += f' Login Username: {employee.user.username}'
                else:
                    msg += ' (No login account created).'
                messages.success(request, msg)
                return redirect('team:employee_detail', pk=employee.pk)
    else:
        form = EmployeeCreateForm()

    return render(request, 'team/employee_form.html', {
        'form': form,
        'form_title': 'Add Employee',
        'is_create': True,
    })


# ---------------------------------------------------------------------------
# Employee detail / Profile
# ---------------------------------------------------------------------------

@login_required
def employee_detail(request, pk):
    """View an employee profile. Accessible by the employee themselves or staff with team:view."""
    employee = get_object_or_404(
        Employee.objects.select_related('user', 'role')
                        .prefetch_related('branches', 'permissions', 'documents'),
        pk=pk,
    )
    if not _can_view_employee(request, employee):
        raise PermissionDenied("You do not have permission to view this employee profile.")

    is_self = (
        hasattr(request.user, 'employee_profile')
        and request.user.employee_profile
        and request.user.employee_profile.pk == employee.pk
    )
    can_edit = has_module_perm(request.user, 'team', 'edit')
    can_manage_perms = can_edit and not is_self and (
        is_admin_user(request.user) or employee.role.name != Role.ROLE_ADMIN
    )

    doc_form = EmployeeDocumentForm()

    return render(request, 'team/employee_detail.html', {
        'employee': employee,
        'permissions': employee.permissions.all(),
        'documents': employee.documents.all(),
        'doc_form': doc_form,
        'is_self': is_self,
        'can_edit': can_edit,
        'can_manage_perms': can_manage_perms,
        'is_admin': is_admin_user(request.user),
    })


# ---------------------------------------------------------------------------
# Employee edit
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'edit')
def employee_edit(request, pk):
    """Edit an employee's business details."""
    employee = get_object_or_404(Employee.objects.select_related('user', 'role'), pk=pk)

    is_self = (
        hasattr(request.user, 'employee_profile')
        and request.user.employee_profile
        and request.user.employee_profile.pk == employee.pk
    )

    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            # Privilege escalation guard:
            new_role = form.cleaned_data.get('role')
            if is_self and new_role != employee.role and not is_admin_user(request.user):
                form.add_error('role', 'You cannot change your own role.')
            elif new_role and new_role.name == Role.ROLE_ADMIN and not is_admin_user(request.user):
                form.add_error('role', 'Only administrators can assign the Admin role.')
            else:
                emp = form.save()
                messages.success(request, f'{emp.full_name} updated successfully.')
                return redirect('team:employee_detail', pk=emp.pk)
    else:
        form = EmployeeEditForm(instance=employee)

    return render(request, 'team/employee_form.html', {
        'form': form,
        'form_title': f'Edit Employee – {employee.full_name}',
        'employee': employee,
        'is_create': False,
    })


# ---------------------------------------------------------------------------
# Activate / Deactivate
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'edit')
def employee_toggle_status(request, pk):
    """POST only: toggle Active ↔ Inactive for an employee."""
    if request.method != 'POST':
        return redirect('team:employee_list')

    employee = get_object_or_404(Employee.objects.select_related('user'), pk=pk)

    # Self-deactivation protection
    if hasattr(request.user, 'employee_profile') and request.user.employee_profile and request.user.employee_profile.pk == employee.pk:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('team:employee_detail', pk=pk)

    if employee.status == Employee.STATUS_ACTIVE:
        employee.deactivate()
        messages.warning(
            request,
            f'{employee.full_name} has been deactivated. '
            f'Their login access has been suspended.'
        )
    else:
        employee.activate()
        messages.success(
            request,
            f'{employee.full_name} has been activated. '
            f'Their login access has been restored.'
        )
    return redirect('team:employee_detail', pk=pk)


# ---------------------------------------------------------------------------
# Password Reset / Set
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'edit')
def employee_password_reset(request, pk):
    """Allows Admin/Manager to directly set/reset the linked User password."""
    employee = get_object_or_404(Employee.objects.select_related('user', 'role'), pk=pk)

    if not employee.user:
        messages.error(request, 'This employee does not have a linked user account.')
        return redirect('team:employee_detail', pk=pk)

    # Protect Admin accounts: only admins can reset another admin's password
    if employee.role.name == Role.ROLE_ADMIN and not is_admin_user(request.user):
        raise PermissionDenied("Only administrators can reset an administrator's password.")

    if request.method == 'POST':
        form = EmployeePasswordResetForm(employee, request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'Password for {employee.full_name} ({employee.user.username}) has been successfully updated.'
            )
            return redirect('team:employee_detail', pk=pk)
    else:
        form = EmployeePasswordResetForm(employee)

    return render(request, 'team/employee_password_reset.html', {
        'employee': employee,
        'form': form,
    })


# ---------------------------------------------------------------------------
# Link / Create User Account for existing unlinked Employee
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'edit')
def employee_link_account(request, pk):
    """Enable login access for an employee who was created without a User account."""
    employee = get_object_or_404(Employee, pk=pk)

    if employee.user:
        messages.info(request, f'{employee.full_name} already has a linked user account ({employee.user.username}).')
        return redirect('team:employee_detail', pk=pk)

    if request.method == 'POST':
        form = EmployeeLinkAccountForm(employee, request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'Login access enabled for {employee.full_name}. Linked account: {employee.user.username}'
            )
            return redirect('team:employee_detail', pk=pk)
    else:
        form = EmployeeLinkAccountForm(employee)

    return render(request, 'team/employee_link_account.html', {
        'employee': employee,
        'form': form,
    })


# ---------------------------------------------------------------------------
# Permissions management
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'edit')
def employee_permissions(request, pk):
    """Admin/Manager manages per-module permissions for one employee."""
    employee = get_object_or_404(Employee.objects.select_related('role'), pk=pk)

    # Self-permission editing protection
    if hasattr(request.user, 'employee_profile') and request.user.employee_profile and request.user.employee_profile.pk == employee.pk:
        raise PermissionDenied("You cannot modify your own permissions.")

    # Only admins can edit permissions of an Admin
    if employee.role.name == Role.ROLE_ADMIN and not is_admin_user(request.user):
        raise PermissionDenied("Only administrators can modify permissions for an Admin.")

    if request.method == 'POST':
        form = PermissionForm(employee, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Permissions updated for {employee.full_name}.')
            return redirect('team:employee_detail', pk=pk)
    else:
        form = PermissionForm(employee)

    # Build grouped rows for template rendering
    rows = []
    for module_key, module_label in EmployeePermission.MODULE_CHOICES:
        row = {'key': module_key, 'label': module_label, 'actions': []}
        for action in PermissionForm.ACTIONS:
            field_name = f'{module_key}__{action}'
            row['actions'].append({
                'name': field_name,
                'label': action.title(),
                'field': form[field_name],
            })
        rows.append(row)

    return render(request, 'team/employee_permissions.html', {
        'employee': employee,
        'form': form,
        'rows': rows,
    })


@login_required
@require_permission('team', 'edit')
def employee_reset_permissions(request, pk):
    """POST only: reset permissions to role defaults."""
    if request.method != 'POST':
        return redirect('team:employee_list')

    employee = get_object_or_404(Employee.objects.select_related('role'), pk=pk)

    # Self-protection
    if hasattr(request.user, 'employee_profile') and request.user.employee_profile and request.user.employee_profile.pk == employee.pk:
        raise PermissionDenied("You cannot modify your own permissions.")

    employee.apply_default_permissions()
    messages.success(request, f'Permissions reset to defaults for role "{employee.role.name}".')
    return redirect('team:employee_permissions', pk=pk)


# ---------------------------------------------------------------------------
# Branch access management
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'edit')
def employee_branches(request, pk):
    """Admin manages which branches an employee can access."""
    employee = get_object_or_404(Employee, pk=pk)
    all_branches = Branch.objects.filter(is_active=True)

    if request.method == 'POST':
        branch_ids = request.POST.getlist('branches')
        employee.branches.set(Branch.objects.filter(pk__in=branch_ids))
        messages.success(request, f'Branch access updated for {employee.full_name}.')
        return redirect('team:employee_detail', pk=pk)

    return render(request, 'team/employee_branches.html', {
        'employee': employee,
        'all_branches': all_branches,
        'current_ids': set(employee.branches.values_list('pk', flat=True)),
    })


# ---------------------------------------------------------------------------
# Roles & Permissions Management (Hub)
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'view')
def role_list(request):
    """Overview of all built-in and custom roles with employee counts and defaults."""
    if not Role.objects.exists():
        Role.ensure_builtin_roles()

    roles = Role.objects.all().prefetch_related('employees')

    role_data = []
    for r in roles:
        defaults = EmployeePermission.default_permissions_for_role(r.name)
        active_modules = [
            mod for mod, flags in defaults.items()
            if any(flags.values())
        ]
        role_data.append({
            'role': r,
            'employee_count': r.employees.count(),
            'active_modules': active_modules,
        })

    return render(request, 'team/role_list.html', {
        'role_data': role_data,
        'can_manage_roles': has_module_perm(request.user, 'team', 'edit'),
    })


@login_required
@require_permission('team', 'edit')
def role_seed(request):
    """Seed or restore default standard roles with one click from the UI."""
    created = Role.ensure_builtin_roles()
    if created > 0:
        messages.success(request, f'Successfully initialized {created} standard role(s).')
    else:
        messages.info(request, 'All standard roles are already initialized.')
    return redirect('team:role_list')


@login_required
@require_permission('team', 'edit')
def role_create(request):
    """Create a new custom role."""
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save(commit=False)
            role.is_builtin = False
            role.save()
            messages.success(request, f'Role "{role.name}" created successfully.')
            return redirect('team:role_list')
    else:
        form = RoleForm()

    return render(request, 'team/role_form.html', {
        'form': form,
        'form_title': 'Add Custom Role',
        'is_create': True,
    })


@login_required
@require_permission('team', 'edit')
def role_edit(request, pk):
    """Edit description or name of a custom role (built-in roles cannot be renamed)."""
    role = get_object_or_404(Role, pk=pk)

    if request.method == 'POST':
        form = RoleForm(request.POST, instance=role)
        if form.is_valid():
            form.save()
            messages.success(request, f'Role "{role.name}" updated.')
            return redirect('team:role_list')
    else:
        form = RoleForm(instance=role)

    return render(request, 'team/role_form.html', {
        'form': form,
        'form_title': f'Edit Role – {role.name}',
        'role': role,
        'is_create': False,
    })


# ---------------------------------------------------------------------------
# HR Foundation: Employee Documents
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'edit')
def employee_document_upload(request, pk):
    """Upload a document to an employee record."""
    employee = get_object_or_404(Employee, pk=pk)

    if request.method == 'POST':
        form = EmployeeDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.employee = employee
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, f'Document "{doc.title}" uploaded.')
        else:
            messages.error(request, 'Error uploading document. Please verify the file.')

    return redirect('team:employee_detail', pk=pk)


@login_required
@require_permission('team', 'delete')
def employee_document_delete(request, pk, doc_pk):
    """POST only: delete an uploaded employee document."""
    if request.method == 'POST':
        doc = get_object_or_404(EmployeeDocument, pk=doc_pk, employee_id=pk)
        title = doc.title
        doc.delete()
        messages.success(request, f'Document "{title}" deleted.')
    return redirect('team:employee_detail', pk=pk)


# ---------------------------------------------------------------------------
# Branch CRUD
# ---------------------------------------------------------------------------

@login_required
@require_permission('team', 'view')
def branch_list(request):
    branches = Branch.objects.all()
    return render(request, 'team/branch_list.html', {'branches': branches})


@login_required
@require_permission('team', 'edit')
def branch_create(request):
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            branch = form.save()
            messages.success(request, f'Branch "{branch.name}" created.')
            return redirect('team:branch_list')
    else:
        form = BranchForm()
    return render(request, 'team/branch_form.html', {
        'form': form,
        'form_title': 'Add Branch',
    })


@login_required
@require_permission('team', 'edit')
def branch_edit(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            messages.success(request, f'Branch "{branch.name}" updated.')
            return redirect('team:branch_list')
    else:
        form = BranchForm(instance=branch)
    return render(request, 'team/branch_form.html', {
        'form': form,
        'form_title': f'Edit Branch – {branch.name}',
        'branch': branch,
    })
