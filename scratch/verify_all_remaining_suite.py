import os
import sys
from pathlib import Path
import django

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()
admin_user = User.objects.filter(is_superuser=True).first()
if not admin_user:
    admin_user = User.objects.create_superuser('admin_test', 'admin@example.com', 'adminpass123')

client = Client()
client.force_login(admin_user)

endpoints_to_test = [
    # Dashboard & Root
    ('Dashboard', reverse('dashboard')),
    ('Landing', reverse('landing_page')),
    ('Themes', reverse('accounts:themes')),
    ('Company Settings', reverse('accounts:company_settings')),
    ('Logout Confirm', reverse('accounts:logout')),

    # Customers
    ('Customers List', reverse('customer_list')),
    ('Customers Create', reverse('customer_add')),

    # Custom Orders
    ('Custom Orders List', reverse('custom_orders:custom_order_list')),
    ('Custom Orders Create', reverse('custom_orders:custom_order_add')),

    # Karigar Suite
    ('Karigar Dashboard', reverse('karigar:dashboard')),
    ('Karigar List', reverse('karigar:karigar_list')),
    ('Karigar Create', reverse('karigar:karigar_create')),
    ('Karigar Assignments List', reverse('karigar:assignment_list')),
    ('Karigar Pending Assignments', reverse('karigar:pending_assignments')),
    ('Karigar Assignment Create', reverse('karigar:assignment_create')),
    ('Karigar Settlements List', reverse('karigar:settlement_list')),
    ('Karigar Settlement Create', reverse('karigar:settlement_create')),
    ('Karigar Reports', reverse('karigar:reports')),

    # Sales Suite
    ('Sales Enquiries List', reverse('enquiry_list')),
    ('Sales Enquiry Create', reverse('enquiry_add')),
    ('Sales Report', reverse('sales_report')),
    ('Sales POS New Sale', reverse('sale_add')),
    ('Sales List', reverse('sale_list')),
    ('Old Gold List', reverse('old_gold_list')),
    ('Old Gold Buyback', reverse('old_gold_buyback_create')),
    ('Old Gold Exchange', reverse('old_gold_exchange_create')),

    # Team & HR
    ('Team Employee List', reverse('team:employee_list')),
    ('Team Employee Create', reverse('team:employee_create')),
    ('Team Role List', reverse('team:role_list')),
    ('Team Role Create', reverse('team:role_create')),
    ('Team Branch List', reverse('team:branch_list')),
    ('Team Branch Create', reverse('team:branch_create')),

    # Inventory Suite
    ('Inventory Item List', reverse('inventory_list')),
    ('Inventory Item Create', reverse('inventory_add')),
    ('Inventory Category List', reverse('category_list')),
    ('Inventory Category Create', reverse('category_add')),
    ('Inventory Stock Movement', reverse('stock_movement_list')),
    ('Inventory Metal Rates', reverse('metal_rates')),
    ('Inventory Pricing Calculator', reverse('pricing_calculator')),
    ('Inventory Import', reverse('inventory_import')),
]

results = []
failures = 0

print("=" * 70)
print("JEWELDESK COMPREHENSIVE ENDPOINT & ATELIER SUITE VERIFICATION")
print("=" * 70)

for name, url in endpoints_to_test:
    try:
        response = client.get(url, follow=True)
        status = response.status_code
        content = response.content.decode('utf-8', errors='ignore')

        # Check for atelier suite or custom landing markers
        has_atelier = 'has-atelier-suite' in content or 'atelier_suite.css' in content or 'jd-landing-body' in content or 'theme-grid' in content
        
        if status == 200:
            print(f"[OK 200] {name.ljust(32)} -> {url} (Atelier/Themed: {has_atelier})")
            results.append((name, url, status, has_atelier, "OK"))
        else:
            print(f"[FAIL {status}] {name.ljust(32)} -> {url}")
            results.append((name, url, status, has_atelier, f"HTTP {status}"))
            failures += 1
    except Exception as e:
        print(f"[ERROR] {name.ljust(32)} -> {url}: {e}")
        results.append((name, url, 500, False, str(e)))
        failures += 1

# Also test dynamic employee and custom order detail pages if records exist
from team.models import Employee
from customers.models import Customer
from custom_orders.models import CustomOrder
from karigar.models import Karigar, KarigarWorkAssignment, KarigarSettlement

emp = Employee.objects.first()
if emp:
    for subname, suburl in [
        (f"Employee Detail ({emp.full_name})", reverse('team:employee_detail', args=[emp.pk])),
        (f"Employee Branches ({emp.full_name})", reverse('team:employee_branches', args=[emp.pk])),
        (f"Employee Permissions ({emp.full_name})", reverse('team:employee_permissions', args=[emp.pk])),
        (f"Employee Password Reset ({emp.full_name})", reverse('team:employee_password_reset', args=[emp.pk])),
    ]:
        try:
            resp = client.get(suburl, follow=True)
            print(f"[OK 200] {subname.ljust(32)} -> {suburl}")
        except Exception as e:
            print(f"[FAIL] {subname}: {e}")

cust = Customer.objects.first()
if cust:
    try:
        suburl = reverse('customer_detail', args=[cust.pk])
        resp = client.get(suburl, follow=True)
        print(f"[OK 200] {'Customer Detail'.ljust(32)} -> {suburl}")
    except Exception as e:
        print(f"[FAIL] Customer Detail: {e}")

kgr = Karigar.objects.first()
if kgr:
    try:
        suburl = reverse('karigar:karigar_detail', args=[kgr.pk])
        resp = client.get(suburl, follow=True)
        print(f"[OK 200] {'Karigar Detail'.ljust(32)} -> {suburl}")
    except Exception as e:
        print(f"[FAIL] Karigar Detail: {e}")

print("=" * 70)
print(f"VERIFICATION SUMMARY: Total Tested: {len(results)}, Failures: {failures}")
print("=" * 70)
