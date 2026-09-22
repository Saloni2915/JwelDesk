from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count, ProtectedError
from .models import Customer
from .forms import CustomerForm


@login_required
def customer_list(request):
    """List all customers with search by name or mobile."""
    customers = Customer.objects.annotate(purchases_count=Count('sales')).order_by('-created_at')

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(mobile__icontains=q))

    # Pagination
    paginator = Paginator(customers, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'customers': page_obj,
        'page_obj': page_obj,
        'selected_q': q,
    }
    return render(request, 'customers/customer_list.html', context)


@login_required
def customer_add(request):
    """Add a new customer."""
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            messages.success(request, f"Customer '{customer.name}' added successfully.")
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm()

    context = {
        'form': form,
        'page_title': 'Add Customer',
        'is_edit': False,
    }
    return render(request, 'customers/customer_form.html', context)


@login_required
def customer_detail(request, pk):
    """View customer profile, purchase history, and enquiries."""
    customer = get_object_or_404(Customer, pk=pk)
    sales = customer.sales.select_related('jewellery_item').order_by('-sale_date')
    enquiries = customer.enquiries.select_related('category').order_by('-created_at')

    context = {
        'customer': customer,
        'sales': sales,
        'enquiries': enquiries,
    }
    return render(request, 'customers/customer_detail.html', context)


@login_required
def customer_edit(request, pk):
    """Edit customer information."""
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            customer = form.save()
            messages.success(request, f"Customer '{customer.name}' updated successfully.")
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm(instance=customer)

    context = {
        'form': form,
        'customer': customer,
        'page_title': f"Edit {customer.name}",
        'is_edit': True,
    }
    return render(request, 'customers/customer_form.html', context)


@login_required
def customer_delete(request, pk):
    """Delete a customer."""
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        cust_name = customer.name
        try:
            customer.delete()
        except ProtectedError:
            messages.error(
                request,
                f"Cannot delete customer '{cust_name}' because they have "
                f"custom orders recorded. Delete or cancel those orders first.")
            return redirect('customer_detail', pk=customer.pk)
        messages.success(request, f"Customer '{cust_name}' deleted successfully.")
        return redirect('customer_list')

    context = {
        'customer': customer,
    }
    return render(request, 'customers/customer_confirm_delete.html', context)

