"""
inventory/dashboard_service.py
------------------------------
Centralized Dashboard Query & Aggregation Service for JewelDesk.

Provides unified, business-type-aware analytics, financial summaries,
stock metrics, recent transactions, and business alerts across Retail,
Wholesale, Purchases, Expenses, and Inventory.
"""

from decimal import Decimal
import datetime
from django.utils import timezone
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Coalesce, TruncDate

from accounts.models import Tenant
from sales.models import Sale, Payment, Enquiry
from inventory.models import JewelleryItem, Category
from inventory import stock, metal_prices
from purchases.models import PurchaseInvoice, Supplier
from outstation.models import ExhibitionExpense
from custom_orders.models import CustomOrder
from team.models import Branch

try:
    from wholesale.models import WholesaleOrder, WholesaleInvoice, RetailerPayment, RetailerParty
    HAS_WHOLESALE = True
except ImportError:
    HAS_WHOLESALE = False


def resolve_date_range(range_key, start_str=None, end_str=None):
    """
    Resolve date filter into (start_date, end_date, range_key, label).
    """
    today = timezone.localdate()
    range_key = (range_key or 'this_month').strip().lower()

    if range_key == 'today':
        return today, today, 'today', 'Today'
    elif range_key == 'yesterday':
        y = today - datetime.timedelta(days=1)
        return y, y, 'yesterday', 'Yesterday'
    elif range_key == '7d':
        return today - datetime.timedelta(days=6), today, '7d', 'Last 7 Days'
    elif range_key == '30d':
        return today - datetime.timedelta(days=29), today, '30d', 'Last 30 Days'
    elif range_key == 'last_month':
        first_this_month = today.replace(day=1)
        last_day_prev = first_this_month - datetime.timedelta(days=1)
        first_day_prev = last_day_prev.replace(day=1)
        return first_day_prev, last_day_prev, 'last_month', 'Last Month'
    elif range_key == 'this_year' or range_key == 'year':
        # Indian Financial Year: April 1 to March 31
        if today.month >= 4:
            fy_start = today.replace(month=4, day=1)
        else:
            fy_start = today.replace(year=today.year - 1, month=4, day=1)
        return fy_start, today, 'this_year', 'This Financial Year'
    elif range_key == 'custom' and start_str and end_str:
        try:
            sd = datetime.date.fromisoformat(start_str.strip())
            ed = datetime.date.fromisoformat(end_str.strip())
            if sd <= ed:
                return sd, ed, 'custom', f"{sd.strftime('%d %b %Y')} – {ed.strftime('%d %b %Y')}"
        except Exception:
            pass

    # Default: This Month
    first_of_month = today.replace(day=1)
    return first_of_month, today, 'this_month', 'This Month'


def get_accessible_branches(request, tenant):
    """Return branches accessible to the user in the current tenant."""
    if not tenant:
        return Branch.objects.none()
    if hasattr(request, 'allowed_branches') and request.allowed_branches:
        return request.allowed_branches
    return Branch.objects.filter(tenant=tenant, is_active=True).order_by('name')


def get_central_dashboard_context(request):
    """
    Construct complete centralized dashboard context respecting tenant,
    business type, branch selection, and date range filters.
    """
    tenant = getattr(request, 'tenant', None)
    today = timezone.localdate()

    # 1. Business Type Identification
    is_retail = getattr(tenant, 'is_retail', True) if tenant else True
    is_wholesale = getattr(tenant, 'is_wholesale', False) if tenant else False
    is_both = is_retail and is_wholesale

    # 2. Date Range Resolution
    range_param = request.GET.get('range', 'this_month')
    custom_start = request.GET.get('start_date')
    custom_end = request.GET.get('end_date')
    start_date, end_date, active_range, range_label = resolve_date_range(range_param, custom_start, custom_end)

    # 3. Branch Filter Resolution
    branches = get_accessible_branches(request, tenant)
    branch_param = (request.GET.get('branch') or '').strip()
    active_b = None
    selected_branch_id = ''

    if branch_param and branch_param.lower() not in ('all', ''):
        try:
            b_obj = branches.filter(id=int(branch_param)).first()
            if b_obj:
                active_b = b_obj
                selected_branch_id = str(b_obj.id)
        except (ValueError, TypeError):
            pass
    elif not getattr(request, 'is_all_branches', False) and hasattr(request, 'branch') and request.branch:
        active_b = request.branch
        selected_branch_id = str(request.branch.id)

    # =========================================================================
    # A. SALES OVERVIEW (Retail + Wholesale)
    # =========================================================================
    retail_sales_amount = Decimal('0.00')
    retail_sales_count = 0
    today_retail_amount = Decimal('0.00')
    today_retail_count = 0
    recent_sales = []

    if is_retail:
        r_sales_qs = Sale.objects.all()
        if tenant:
            r_sales_qs = r_sales_qs.filter(tenant=tenant)
        if active_b:
            r_sales_qs = r_sales_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))

        period_r_sales = r_sales_qs.filter(sale_date__date__gte=start_date, sale_date__date__lte=end_date)
        r_agg = period_r_sales.aggregate(
            total=Coalesce(Sum('sale_price'), Decimal('0.00')),
            count=Count('id')
        )
        retail_sales_amount = r_agg['total'] or Decimal('0.00')
        retail_sales_count = r_agg['count'] or 0

        # Today's Retail
        today_r = r_sales_qs.filter(sale_date__date=today).aggregate(
            total=Coalesce(Sum('sale_price'), Decimal('0.00')),
            count=Count('id')
        )
        today_retail_amount = today_r['total'] or Decimal('0.00')
        today_retail_count = today_r['count'] or 0

        # Recent 6 Retail Sales
        recent_sales = list(
            r_sales_qs.select_related('customer', 'jewellery_item')
            .prefetch_related('payments')
            .order_by('-sale_date')[:6]
        )

    wholesale_sales_amount = Decimal('0.00')
    wholesale_sales_count = 0
    today_wholesale_amount = Decimal('0.00')
    today_wholesale_count = 0
    recent_wholesale_orders = []

    if is_wholesale and HAS_WHOLESALE and tenant:
        w_orders_qs = WholesaleOrder.objects.filter(tenant=tenant).exclude(status='CANCELLED')
        # Filter by branch if applicable
        if active_b and hasattr(WholesaleOrder, 'branch'):
            w_orders_qs = w_orders_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))

        period_w_orders = w_orders_qs.filter(order_date__gte=start_date, order_date__lte=end_date)
        w_agg = period_w_orders.aggregate(
            total=Coalesce(Sum('total_amount'), Decimal('0.00')),
            count=Count('id')
        )
        wholesale_sales_amount = w_agg['total'] or Decimal('0.00')
        wholesale_sales_count = w_agg['count'] or 0

        # Today's Wholesale
        today_w = w_orders_qs.filter(order_date=today).aggregate(
            total=Coalesce(Sum('total_amount'), Decimal('0.00')),
            count=Count('id')
        )
        today_wholesale_amount = today_w['total'] or Decimal('0.00')
        today_wholesale_count = today_w['count'] or 0

        # Recent 6 Wholesale Orders
        recent_wholesale_orders = list(
            w_orders_qs.select_related('party')
            .order_by('-created_at')[:6]
        )

    # Combined Sales Totals
    total_sales_amount = retail_sales_amount + wholesale_sales_amount
    total_sales_count = retail_sales_count + wholesale_sales_count
    today_sales_amount = today_retail_amount + today_wholesale_amount
    today_sales_count = today_retail_count + today_wholesale_count

    # =========================================================================
    # B. PURCHASES & PROCUREMENT OVERVIEW
    # =========================================================================
    total_purchases_amount = Decimal('0.00')
    total_purchases_count = 0
    today_purchases_amount = Decimal('0.00')
    today_purchases_count = 0
    recent_purchases = []
    due_purchases = []

    if tenant:
        purchases_qs = PurchaseInvoice.objects.filter(tenant=tenant).exclude(status='CANCELLED')
        if active_b:
            purchases_qs = purchases_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))

        period_purchases = purchases_qs.filter(purchase_date__gte=start_date, purchase_date__lte=end_date)
        p_agg = period_purchases.aggregate(
            total=Coalesce(Sum('grand_total'), Decimal('0.00')),
            count=Count('id')
        )
        total_purchases_amount = p_agg['total'] or Decimal('0.00')
        total_purchases_count = p_agg['count'] or 0

        today_p = purchases_qs.filter(purchase_date=today).aggregate(
            total=Coalesce(Sum('grand_total'), Decimal('0.00')),
            count=Count('id')
        )
        today_purchases_amount = today_p['total'] or Decimal('0.00')
        today_purchases_count = today_p['count'] or 0

        recent_purchases = list(
            purchases_qs.select_related('supplier', 'branch')
            .order_by('-purchase_date', '-id')[:6]
        )
        due_purchases = list(
            purchases_qs.filter(status__in=['CONFIRMED', 'PARTIALLY_PAID'], balance_amount__gt=0)
            .select_related('supplier', 'branch')
            .order_by('due_date')[:5]
        )

    # =========================================================================
    # C. EXPENSES OVERVIEW
    # =========================================================================
    total_expenses_amount = Decimal('0.00')
    total_expenses_count = 0

    if tenant:
        exp_qs = ExhibitionExpense.objects.filter(tenant=tenant)
        period_exp = exp_qs.filter(expense_date__gte=start_date, expense_date__lte=end_date)
        e_agg = period_exp.aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00')),
            count=Count('id')
        )
        total_expenses_amount = e_agg['total'] or Decimal('0.00')
        total_expenses_count = e_agg['count'] or 0

    # =========================================================================
    # D. PAYMENTS RECEIVED & COLLECTIONS (Period)
    # =========================================================================
    retail_payments = Decimal('0.00')
    wholesale_payments = Decimal('0.00')
    payment_mode_breakdown = {}

    if is_retail and tenant:
        r_pay_qs = Payment.objects.filter(tenant=tenant)
        if active_b:
            r_pay_qs = r_pay_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))
        period_r_pay = r_pay_qs.filter(payment_date__date__gte=start_date, payment_date__date__lte=end_date)
        retail_payments = period_r_pay.aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00'))
        )['total'] or Decimal('0.00')

        # Mode summary
        mode_counts = period_r_pay.values('payment_method').annotate(sum=Sum('amount')).order_by('-sum')
        for m in mode_counts:
            k = m['payment_method'] or 'Other'
            payment_mode_breakdown[k] = payment_mode_breakdown.get(k, Decimal('0.00')) + (m['sum'] or Decimal('0.00'))

    if is_wholesale and HAS_WHOLESALE and tenant:
        w_pay_qs = RetailerPayment.objects.filter(tenant=tenant)
        period_w_pay = w_pay_qs.filter(payment_date__gte=start_date, payment_date__lte=end_date)
        wholesale_payments = period_w_pay.aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00'))
        )['total'] or Decimal('0.00')

        w_modes = period_w_pay.values('payment_method').annotate(sum=Sum('amount')).order_by('-sum')
        for m in w_modes:
            k = m['payment_method'] or 'Bank'
            payment_mode_breakdown[k] = payment_mode_breakdown.get(k, Decimal('0.00')) + (m['sum'] or Decimal('0.00'))

    total_payments_received = retail_payments + wholesale_payments

    # =========================================================================
    # E. OUTSTANDING BALANCES (Receivables vs Payables)
    # =========================================================================
    retail_outstanding = Decimal('0.00')
    wholesale_outstanding = Decimal('0.00')

    if is_retail and tenant:
        # Lifetime sales minus lifetime payments
        all_sales = Sale.objects.filter(tenant=tenant)
        all_payments = Payment.objects.filter(tenant=tenant)
        if active_b:
            all_sales = all_sales.filter(Q(branch=active_b) | Q(branch__isnull=True))
            all_payments = all_payments.filter(Q(branch=active_b) | Q(branch__isnull=True))

        tot_s = all_sales.aggregate(tot=Coalesce(Sum('sale_price'), Decimal('0.00')))['tot']
        tot_p = all_payments.aggregate(tot=Coalesce(Sum('amount'), Decimal('0.00')))['tot']
        retail_outstanding = max(Decimal('0.00'), tot_s - tot_p)

    if is_wholesale and HAS_WHOLESALE and tenant:
        active_parties = RetailerParty.objects.filter(tenant=tenant, is_active=True)
        party_ids = list(active_parties.values_list('id', flat=True))
        if party_ids:
            tot_open = active_parties.aggregate(tot=Coalesce(Sum('opening_balance'), Decimal('0.00')))['tot']
            tot_inv = WholesaleInvoice.objects.filter(
                tenant=tenant, party_id__in=party_ids
            ).exclude(status='CANCELLED').aggregate(tot=Coalesce(Sum('total_amount'), Decimal('0.00')))['tot']
            tot_paid = RetailerPayment.objects.filter(
                tenant=tenant, party_id__in=party_ids
            ).aggregate(tot=Coalesce(Sum('amount'), Decimal('0.00')))['tot']
            wholesale_outstanding = max(Decimal('0.00'), tot_open + tot_inv - tot_paid)

    total_receivables = retail_outstanding + wholesale_outstanding

    # Supplier Payables (Purchases)
    total_payables = Decimal('0.00')
    if tenant:
        supp_qs = Supplier.objects.filter(tenant=tenant, is_active=True)
        if active_b:
            supp_qs = supp_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))
        total_payables = supp_qs.filter(current_balance__gt=0).aggregate(
            tot=Coalesce(Sum('current_balance'), Decimal('0.00'))
        )['tot'] or Decimal('0.00')

    # Legacy alias
    outstanding_amount = total_receivables

    # =========================================================================
    # F. CURRENT INVENTORY & STOCK SUMMARY
    # =========================================================================
    available_items = 0
    inventory_value = Decimal('0.00')
    gold_weight_g = Decimal('0.00')
    silver_weight_g = Decimal('0.00')
    total_items = 0
    sold_items = 0
    low_stock_designs = []
    low_stock_design_count = 0

    stock_summary = stock.inventory_summary(tenant=tenant, branch=active_b, use_cache=True)
    total_items = stock_summary.get('total_items', 0)
    available_items = stock_summary.get('available_stock', 0)
    inventory_value = stock_summary.get('inventory_value', Decimal('0.00'))
    low_stock_designs = stock_summary.get('low_stock_designs', [])[:5]
    low_stock_design_count = stock_summary.get('low_stock_design_count', 0)

    # Available items weights breakdown
    avail_qs = JewelleryItem.objects.filter(status='Available')
    if tenant:
        avail_qs = avail_qs.filter(tenant=tenant)
    if active_b:
        avail_qs = avail_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))

    weights_agg = avail_qs.aggregate(
        gold_wt=Coalesce(Sum('net_weight', filter=Q(metal_type__iexact='Gold')), Decimal('0.00')),
        silver_wt=Coalesce(Sum('net_weight', filter=Q(metal_type__iexact='Silver')), Decimal('0.00'))
    )
    gold_weight_g = weights_agg['gold_wt'] or Decimal('0.00')
    silver_weight_g = weights_agg['silver_wt'] or Decimal('0.00')

    # Sold items in period
    sold_qs = JewelleryItem.objects.filter(status='Sold')
    if tenant:
        sold_qs = sold_qs.filter(tenant=tenant)
    if active_b:
        sold_qs = sold_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))
    sold_items = sold_qs.count()

    # =========================================================================
    # G. BUSINESS PROFIT & SURPLUS SUMMARY
    # =========================================================================
    # Operating Surplus = Total Sales - Total Purchases - Total Expenses
    operating_surplus = total_sales_amount - (total_purchases_amount + total_expenses_amount)

    # Item Gross Profit (Only where cost_price is reliably recorded)
    realized_gross_profit = Decimal('0.00')
    has_cost_data = False

    # =========================================================================
    # H. BUSINESS ALERTS & PENDING ACTIVITIES
    # =========================================================================
    pending_custom_orders_count = 0
    pending_custom_orders = []
    if is_retail and tenant:
        po_qs = (
            CustomOrder.objects.filter(tenant=tenant)
            .select_related('customer', 'category')
            .exclude(status__in=[CustomOrder.STATUS_DELIVERED, CustomOrder.STATUS_CANCELLED])
        )
        if active_b:
            po_qs = po_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))
        pending_custom_orders_count = po_qs.count()
        pending_custom_orders = list(po_qs.order_by('expected_delivery_date', '-created_at')[:5])

    pending_wholesale_orders_count = 0
    if is_wholesale and HAS_WHOLESALE and tenant:
        pending_wholesale_orders_count = WholesaleOrder.objects.filter(
            tenant=tenant,
            status__in=['DRAFT', 'CONFIRMED', 'PROCESSING', 'READY_FOR_DISPATCH']
        ).count()

    recent_enquiries = []
    upcoming_followups = []
    if is_retail and tenant:
        enq_qs = Enquiry.objects.filter(tenant=tenant)
        if active_b:
            enq_qs = enq_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))
        recent_enquiries = list(enq_qs.select_related('customer', 'category').order_by('-created_at')[:5])
        upcoming_followups = list(
            enq_qs.select_related('customer', 'category')
            .filter(next_followup_date__gte=today)
            .exclude(status__in=['Purchased', 'Closed'])
            .order_by('next_followup_date')[:5]
        )

    # =========================================================================
    # I. 7-DAY REVENUE ANALYTICS CHART
    # =========================================================================
    week_start = today - datetime.timedelta(days=6)
    sales_chart = []
    chart_max = 0

    if tenant:
        # Retail daily
        r_per_day = {}
        if is_retail:
            r_day_qs = Sale.objects.filter(
                tenant=tenant,
                sale_date__date__gte=week_start,
                sale_date__date__lte=today
            )
            if active_b:
                r_day_qs = r_day_qs.filter(Q(branch=active_b) | Q(branch__isnull=True))
            r_rows = r_day_qs.annotate(day=TruncDate('sale_date')).values('day').annotate(
                total=Sum('sale_price'), count=Count('id')
            )
            r_per_day = {row['day']: row for row in r_rows}

        # Wholesale daily
        w_per_day = {}
        if is_wholesale and HAS_WHOLESALE:
            w_day_qs = WholesaleOrder.objects.filter(
                tenant=tenant,
                order_date__gte=week_start,
                order_date__lte=today
            ).exclude(status='CANCELLED')
            w_rows = w_day_qs.values('order_date').annotate(
                total=Sum('total_amount'), count=Count('id')
            )
            w_per_day = {row['order_date']: row for row in w_rows}

        for i in range(7):
            d = week_start + datetime.timedelta(days=i)
            r_item = r_per_day.get(d, {})
            w_item = w_per_day.get(d, {})
            tot = (r_item.get('total') or Decimal('0.00')) + (w_item.get('total') or Decimal('0.00'))
            cnt = (r_item.get('count') or 0) + (w_item.get('count') or 0)
            sales_chart.append({
                'date': d,
                'label': d.strftime('%a'),
                'day_num': d.strftime('%d'),
                'total': tot,
                'count': cnt,
                'retail_total': r_item.get('total') or Decimal('0.00'),
                'wholesale_total': w_item.get('total') or Decimal('0.00'),
            })

        chart_max = max([float(r['total'] or 0) for r in sales_chart] + [0])
        for row in sales_chart:
            val = float(row['total'] or 0)
            row['pct'] = round((val / chart_max * 100)) if chart_max else 0

    # Live Metal Rates snapshot
    metal_price_snapshot = metal_prices.get_price_snapshot()

    return {
        'page_title': 'Central Dashboard',
        'tenant': tenant,
        'today': today,

        # Business Model Flags
        'is_retail': is_retail,
        'is_wholesale': is_wholesale,
        'is_both': is_both,

        # Filter Context
        'active_range': active_range,
        'range_label': range_label,
        'start_date': start_date,
        'end_date': end_date,
        'branches': branches,
        'active_branch': active_b,
        'selected_branch_id': selected_branch_id,

        # Unified Financial Highlights
        'total_sales_amount': total_sales_amount,
        'total_sales_count': total_sales_count,
        'today_sales_amount': today_sales_amount,
        'today_sales_count': today_sales_count,

        'retail_sales_amount': retail_sales_amount,
        'retail_sales_count': retail_sales_count,
        'wholesale_sales_amount': wholesale_sales_amount,
        'wholesale_sales_count': wholesale_sales_count,

        'total_purchases_amount': total_purchases_amount,
        'total_purchases_count': total_purchases_count,
        'today_purchases_amount': today_purchases_amount,
        'today_purchases_count': today_purchases_count,

        'total_expenses_amount': total_expenses_amount,
        'total_expenses_count': total_expenses_count,

        'total_payments_received': total_payments_received,
        'retail_payments': retail_payments,
        'wholesale_payments': wholesale_payments,
        'payment_mode_breakdown': payment_mode_breakdown,

        'total_receivables': total_receivables,
        'retail_outstanding': retail_outstanding,
        'wholesale_outstanding': wholesale_outstanding,
        'total_payables': total_payables,
        'outstanding_amount': outstanding_amount,  # legacy alias

        'operating_surplus': operating_surplus,
        'realized_gross_profit': realized_gross_profit,
        'has_cost_data': has_cost_data,

        # Stock Overview
        'total_items': total_items,
        'available_items': available_items,
        'sold_items': sold_items,
        'inventory_value': inventory_value,
        'gold_weight_g': gold_weight_g,
        'silver_weight_g': silver_weight_g,
        'low_stock_designs': low_stock_designs,
        'low_stock_design_count': low_stock_design_count,

        # Recent Transactions
        'recent_sales': recent_sales,
        'recent_wholesale_orders': recent_wholesale_orders,
        'recent_purchases': recent_purchases,
        'due_purchases': due_purchases,

        # Pending Activities & Alerts
        'pending_custom_orders': pending_custom_orders,
        'pending_custom_orders_count': pending_custom_orders_count,
        'pending_wholesale_orders_count': pending_wholesale_orders_count,
        'recent_enquiries': recent_enquiries,
        'upcoming_followups': upcoming_followups,

        # Chart & Rates
        'sales_chart': sales_chart,
        'sales_chart_max': chart_max,
        'sales_chart_start': week_start,
        'metal_prices': metal_price_snapshot,
    }
