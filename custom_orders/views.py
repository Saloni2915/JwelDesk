from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from .forms import CustomOrderForm, CustomOrderStatusForm
from .models import CustomOrder


CUSTOM_ORDERS_PER_PAGE = 15


@login_required
def custom_order_list(request):
    """List custom orders with search, status, and expected-delivery filters."""
    orders = CustomOrder.objects.select_related('customer', 'category').all()
    today = timezone.localdate()

    q = request.GET.get('q', '').strip()
    if q:
        orders = orders.filter(
            Q(customer__name__icontains=q)
            | Q(customer__mobile__icontains=q)
            | Q(order_number__icontains=q)
            | Q(design_description__icontains=q)
        )

    status = request.GET.get('status', '').strip()
    if status:
        orders = orders.filter(status=status)

    delivery = request.GET.get('delivery', '').strip()
    if delivery == 'due_this_week':
        week_end = today + timedelta(days=7)
        orders = orders.filter(expected_delivery_date__range=(today, week_end))
    elif delivery == 'overdue':
        orders = orders.filter(expected_delivery_date__lt=today).exclude(
            status__in=[CustomOrder.STATUS_DELIVERED, CustomOrder.STATUS_CANCELLED])

    paginator = Paginator(orders, CUSTOM_ORDERS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Custom Orders',
        'orders': page_obj,
        'page_obj': page_obj,
        'status_choices': CustomOrder.STATUS_CHOICES,
        'selected_q': q,
        'selected_status': status,
        'selected_delivery': delivery,
    }
    return render(request, 'custom_orders/custom_order_list.html', context)


@login_required
def custom_order_add(request):
    """Create a new custom order; status always starts at Enquiry."""
    initial = {}
    customer_param = request.GET.get('customer', '').strip()
    if customer_param.isdigit():
        initial['customer'] = int(customer_param)

    if request.method == 'POST':
        form = CustomOrderForm(request.POST, request.FILES)
        if form.is_valid():
            order = form.save(commit=False)
            order.status = CustomOrder.STATUS_ENQUIRY
            order.save()
            messages.success(
                request,
                f"Custom order {order.order_number} for '{order.customer.name}' created successfully.")
            return redirect('custom_orders:custom_order_detail', pk=order.pk)
        messages.error(request, "Could not create the custom order. Please fix the errors below.")
    else:
        form = CustomOrderForm(initial=initial)

    context = {
        'form': form,
        'page_title': 'New Custom Order',
        'is_edit': False,
    }
    return render(request, 'custom_orders/custom_order_form.html', context)


@login_required
def custom_order_detail(request, pk):
    """Show the full order with allowed next statuses."""
    order = get_object_or_404(
        CustomOrder.objects.select_related('customer', 'category'), pk=pk)
    # Only offer transitions allowed by the shop workflow, in workflow order.
    status_map = dict(CustomOrder.STATUS_CHOICES)
    allowed_statuses = [
        key for key, _label in CustomOrder.STATUS_CHOICES
        if order.can_transition_to(key)
    ]
    if allowed_statuses:
        status_form = CustomOrderStatusForm(initial={'status': order.status})
        status_form.fields['status'].choices = [
            (key, status_map[key]) for key in allowed_statuses
        ]
    else:
        status_form = None
    context = {
        'order': order,
        'status_form': status_form,
        'allowed_statuses': allowed_statuses,
        'reference_is_pdf': bool(
            order.reference_image and order.reference_image.name.lower().endswith('.pdf')),
        'today': timezone.localdate(),
    }
    return render(request, 'custom_orders/custom_order_detail.html', context)


@login_required
def custom_order_edit(request, pk):
    """Edit a custom order; delivered/cancelled orders are read-only."""
    order = get_object_or_404(CustomOrder, pk=pk)
    if order.status in (CustomOrder.STATUS_DELIVERED, CustomOrder.STATUS_CANCELLED):
        messages.error(
            request,
            f"Custom order {order.order_number} is {order.status} and can no longer be edited.")
        return redirect('custom_orders:custom_order_detail', pk=order.pk)

    if request.method == 'POST':
        form = CustomOrderForm(request.POST, request.FILES, instance=order)
        if form.is_valid():
            order = form.save()
            messages.success(
                request,
                f"Custom order {order.order_number} updated successfully.")
            return redirect('custom_orders:custom_order_detail', pk=order.pk)
        messages.error(request, "Could not update the custom order. Please fix the errors below.")
    else:
        form = CustomOrderForm(instance=order)

    context = {
        'form': form,
        'order': order,
        'page_title': f"Edit {order.order_number}",
        'is_edit': True,
    }
    return render(request, 'custom_orders/custom_order_form.html', context)


@login_required
def custom_order_delete(request, pk):
    """Delete a draft-stage order, or cancel an order already in progress."""
    order = get_object_or_404(CustomOrder, pk=pk)

    if request.method == 'POST':
        if order.status in (CustomOrder.STATUS_DELIVERED, CustomOrder.STATUS_CANCELLED):
            messages.error(
                request,
                f"Custom order {order.order_number} is {order.status} and cannot be deleted.")
            return redirect('custom_orders:custom_order_detail', pk=order.pk)
        if order.status in (CustomOrder.STATUS_ENQUIRY, CustomOrder.STATUS_ESTIMATE):
            order_number = order.order_number
            order.delete()
            messages.success(
                request,
                f"Custom order {order_number} deleted successfully.")
            return redirect('custom_orders:custom_order_list')
        try:
            order.set_status(CustomOrder.STATUS_CANCELLED)
        except ValidationError as exc:
            messages.error(request, f"Could not cancel the order. {exc.messages[0]}")
            return redirect('custom_orders:custom_order_detail', pk=order.pk)
        messages.success(
            request,
            f"Custom order {order.order_number} cancelled successfully.")
        return redirect('custom_orders:custom_order_detail', pk=order.pk)

    context = {
        'order': order,
        'allowed_statuses': order.get_allowed_statuses(),
    }
    return render(request, 'custom_orders/custom_order_confirm_delete.html', context)


@login_required
def custom_order_status(request, pk):
    """Change the order status, enforcing the allowed shop workflow."""
    order = get_object_or_404(CustomOrder, pk=pk)
    if request.method != 'POST':
        return redirect('custom_orders:custom_order_detail', pk=order.pk)

    form = CustomOrderStatusForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please choose a valid status.")
        return redirect('custom_orders:custom_order_detail', pk=order.pk)

    new_status = form.cleaned_data['status']
    try:
        changed = order.set_status(new_status)
    except ValidationError as exc:
        messages.error(request, f"Status not changed. {exc.messages[0]}")
        return redirect('custom_orders:custom_order_detail', pk=order.pk)

    if changed:
        messages.success(
            request,
            f"Custom order {order.order_number} is now '{order.status}'.")
    else:
        messages.info(request, f"Custom order {order.order_number} is already '{order.status}'.")
    return redirect('custom_orders:custom_order_detail', pk=order.pk)