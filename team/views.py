"""
team/views.py
-------------
All views for the Team / Employee Management module.

Access control:
  - All views require login_required.
  - Most views require staff_required (is_active + is_staff).
  - Employee detail is viewable by the employee themselves.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import (
    BranchForm,
    EmployeeCreateForm,
    EmployeeEditForm,
    PermissionForm,
)
from .models import Branch, Employee, EmployeePermission, Role

User = get_user_model()

# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

staff_required = user_passes_test(
    lambda u: u.is_active and u.is_staff,
    login_url='accounts:login',
)


def _is_self_or_staff(request, employee):
    """True if the request user owns this employee record or is staff."""
    return request.user.is_staff or (
        hasattr(request.user, 'employee_profile')
        and request.user.employee_profile.pk == employee.pk
    )


# ---------------------------------------------------------------------------
# Employee list
# ---------------------------------------------------------------------------

@login_required
@staff_required
def employee_list(request):
    """Show all employees with search/filter."""
    qs = Employee.objects.select_related('user', 'role').prefetch_related('branches')

    q        = request.GET.get('q', '').strip()
    role_id  = request.GET.get('role', '').strip()
    status   = request.GET.get('status', '').strip()
    branch_id = request.GET.get('branch', '').strip()

    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(full_name__icontains=q) |
            Q(employee_id__icontains=q) |
            Q(email__icontains=q) |
            Q(mobile__icontains=q)
        )
    if role_id:
        qs = qs.filter(role_id=role_id)
    if status:
        qs = qs.filter(status=status)
    if branch_id:
        qs = qs.filter(branches__id=branch_id)

    paginator = Paginator(qs, 20)
    page      = paginator.get_page(request.GET.get('page'))

    return render(request, 'team/employee_list.html', {
        'page_obj':    page,
        'employees':   page.object_list,
        'roles':       Role.objects.all(),
        'branches':    Branch.objects.filter(is_active=True),
        'statuses':    Employee.STATUS_CHOICES,
        'q':           q,
        'sel_role':    role_id,
        'sel_status':  status,
        'sel_branch':  branch_id,
        'total_count': qs.count(),
    })


# ---------------------------------------------------------------------------
# Employee create
# ---------------------------------------------------------------------------

@login_required
@staff_required
def employee_create(request):
    """Admin creates a new employee (and the linked Django User)."""
    if request.method == 'POST':
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            employee = form.save(created_by=request.user)
            messages.success(
                request,
                f'Employee {employee.full_name} ({employee.employee_id}) '
                f'created successfully. Username: {employee.user.username}'
            )
            return redirect('team:employee_detail', pk=employee.pk)
    else:
        form = EmployeeCreateForm()

    return render(request, 'team/employee_form.html', {
        'form':       form,
        'form_title': 'Add Employee',
        'is_create':  True,
    })


# ---------------------------------------------------------------------------
# Employee detail
# ---------------------------------------------------------------------------

@login_required
def employee_detail(request, pk):
    """View an employee's profile. Staff or the employee themselves."""
    employee = get_object_or_404(
        Employee.objects.select_related('user', 'role')
                        .prefetch_related('branches', 'permissions'),
        pk=pk,
    )
    if not _is_self_or_staff(request, employee):
        messages.error(request, 'You do not have permission to view this profile.')
        return redirect('dashboard')

    return render(request, 'team/employee_detail.html', {
        'employee':    employee,
        'permissions': employee.permissions.all(),
    })


# ---------------------------------------------------------------------------
# Employee edit
# ---------------------------------------------------------------------------

@login_required
@staff_required
def employee_edit(request, pk):
    """Admin edits an employee's business details."""
    employee = get_object_or_404(Employee, pk=pk)

    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, instance=employee)
        if form.is_valid():
            emp = form.save()
            messages.success(request, f'{emp.full_name} updated successfully.')
            return redirect('team:employee_detail', pk=emp.pk)
    else:
        form = EmployeeEditForm(instance=employee)

    return render(request, 'team/employee_form.html', {
        'form':       form,
        'form_title': f'Edit Employee – {employee.full_name}',
        'employee':   employee,
        'is_create':  False,
    })


# ---------------------------------------------------------------------------
# Activate / Deactivate
# ---------------------------------------------------------------------------

@login_required
@staff_required
def employee_toggle_status(request, pk):
    """POST only: toggle Active ↔ Inactive for an employee."""
    if request.method != 'POST':
        return redirect('team:employee_list')

    employee = get_object_or_404(Employee, pk=pk)

    if employee.status == Employee.STATUS_ACTIVE:
        employee.deactivate()
        messages.warning(
            request,
            f'{employee.full_name} has been deactivated. '
            f'They can no longer log in.'
        )
    else:
        employee.activate()
        messages.success(
            request,
            f'{employee.full_name} has been activated.'
        )
    return redirect('team:employee_detail', pk=pk)


# ---------------------------------------------------------------------------
# Permissions management
# ---------------------------------------------------------------------------

@login_required
@staff_required
def employee_permissions(request, pk):
    """Admin manages per-module permissions for one employee."""
    employee = get_object_or_404(Employee, pk=pk)

    if request.method == 'POST':
        form = PermissionForm(employee, request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'Permissions updated for {employee.full_name}.'
            )
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
                'name':    field_name,
                'label':   action.title(),
                'field':   form[field_name],
            })
        rows.append(row)

    return render(request, 'team/employee_permissions.html', {
        'employee': employee,
        'form':     form,
        'rows':     rows,
    })


@login_required
@staff_required
def employee_reset_permissions(request, pk):
    """POST only: reset permissions to role defaults."""
    if request.method != 'POST':
        return redirect('team:employee_list')

    employee = get_object_or_404(Employee, pk=pk)
    employee.apply_default_permissions()
    messages.success(
        request,
        f'Permissions reset to defaults for role "{employee.role.name}".'
    )
    return redirect('team:employee_permissions', pk=pk)


# ---------------------------------------------------------------------------
# Branch access management
# ---------------------------------------------------------------------------

@login_required
@staff_required
def employee_branches(request, pk):
    """Admin manages which branches an employee can access."""
    employee = get_object_or_404(Employee, pk=pk)
    all_branches = Branch.objects.filter(is_active=True)

    if request.method == 'POST':
        branch_ids = request.POST.getlist('branches')
        employee.branches.set(Branch.objects.filter(pk__in=branch_ids))
        messages.success(
            request,
            f'Branch access updated for {employee.full_name}.'
        )
        return redirect('team:employee_detail', pk=pk)

    return render(request, 'team/employee_branches.html', {
        'employee':     employee,
        'all_branches': all_branches,
        'current_ids':  set(employee.branches.values_list('pk', flat=True)),
    })


# ---------------------------------------------------------------------------
# Branch CRUD
# ---------------------------------------------------------------------------

@login_required
@staff_required
def branch_list(request):
    branches = Branch.objects.all()
    return render(request, 'team/branch_list.html', {'branches': branches})


@login_required
@staff_required
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
        'form':       form,
        'form_title': 'Add Branch',
    })


@login_required
@staff_required
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
        'form':       form,
        'form_title': f'Edit Branch – {branch.name}',
        'branch':     branch,
    })
