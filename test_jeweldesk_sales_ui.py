"""
test_jeweldesk_sales_ui.py
--------------------------
Real Browser-based Selenium WebDriver Automation Test Suite for JewelDesk.
Tests end-to-end user workflow:
  1. Login with dedicated test account
  2. Navigate to Inventory and select an Available jewellery item
  3. Initiate and populate POS Sales Billing form with test customer
  4. Submit sale transaction
  5. Verify Sale Confirmation Invoice receipt
  6. Verify Inventory status transition according to JewelDesk application logic (Available -> Sold)

Target: Local Development Environment (Safe SQLite Database)
Framework: pytest + Selenium WebDriver 4
"""

import os
import sys
import time
import pytest

# 1. Initialize Django environment so test fixtures can safely seed/reset local test data
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from accounts.models import Tenant, CompanySettings
from inventory.models import JewelleryItem, Category
from customers.models import Customer
from sales.models import Sale

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager


# Safety Assertion: Ensure the test runs strictly against local SQLite, NEVER production!
assert 'sqlite' in settings.DATABASES['default']['ENGINE'].lower(), (
    "SAFETY GUARD TRIGGERED: This automated test must only run against the local SQLite test database!"
)

BASE_URL = os.environ.get('JEWELDESK_TEST_URL', 'http://127.0.0.1:8000')
TEST_USERNAME = 'selenium_test_user'
TEST_PASSWORD = 'SeleniumTest@123'
TEST_TAG_NUMBER = 'SEL-KADA-001'
TEST_CUSTOMER_NAME = 'Selenium Test Customer'
TEST_CUSTOMER_PHONE = '9898989898'


@pytest.fixture(scope='function')
def test_data_fixture():
    """
    Sets up dedicated, isolated test data in the local database before running the test,
    and resets the jewellery item to 'Available' with quantity=1 so the test is 100% idempotent.
    """
    User = get_user_model()
    user, _ = User.objects.get_or_create(username=TEST_USERNAME)
    user.set_password(TEST_PASSWORD)
    user.email = 'selenium_qa@jeweldesk.local'
    user.is_staff = True
    user.save()

    tenant, _ = Tenant.objects.get_or_create(
        name='Selenium Test Jewellery',
        defaults={'owner': user, 'business_type': Tenant.TYPE_RETAIL}
    )
    if tenant.owner != user:
        tenant.owner = user
        tenant.save()

    CompanySettings.objects.get_or_create(
        tenant=tenant,
        defaults={'company_name': 'Selenium Test Jewellery'}
    )

    cat, _ = Category.objects.get_or_create(
        tenant=tenant,
        name='Bangles & Kadas'
    )

    item, _ = JewelleryItem.objects.get_or_create(
        tenant=tenant,
        tag_number=TEST_TAG_NUMBER,
        defaults={
            'name': 'Selenium Test Gold Kada',
            'item_code': TEST_TAG_NUMBER,
            'category': cat,
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight': 15.500,
            'net_weight': 15.500,
            'selling_price': 85000.00,
            'quantity': 1,
            'status': 'Available',
        }
    )
    # Always reset state before test run
    item.status = 'Available'
    item.quantity = 1
    item.selling_price = 85000.00
    item.save()

    cust, _ = Customer.objects.get_or_create(
        tenant=tenant,
        mobile=TEST_CUSTOMER_PHONE,
        defaults={
            'name': TEST_CUSTOMER_NAME,
            'address': 'MG Road, Test City'
        }
    )
    if cust.name != TEST_CUSTOMER_NAME:
        cust.name = TEST_CUSTOMER_NAME
        cust.save()

    return {
        'user': user,
        'tenant': tenant,
        'item': item,
        'customer': cust,
    }


@pytest.fixture(scope='function')
def driver():
    """
    Initializes a real Google Chrome WebDriver instance in headless mode,
    configures clean timeouts, and cleans up on completion.
    """
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')

    service = Service(ChromeDriverManager().install())
    browser = webdriver.Chrome(service=service, options=chrome_options)
    browser.implicitly_wait(2)

    yield browser

    browser.quit()


# Helper utilities to prevent flaky StaleElementReferenceException during dynamic DOM hydration
def safe_type(driver, by, selector, text, timeout=10):
    """Safely type text into an input field handling asynchronous page transitions."""
    for _ in range(4):
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, selector))
            )
            element.clear()
            element.send_keys(text)
            return element
        except (StaleElementReferenceException, WebDriverException):
            time.sleep(0.5)
    raise


def safe_click(driver, by, selector, timeout=10):
    """Safely click an element using native click or JavaScript fallback if overlaid."""
    for _ in range(4):
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, selector))
            )
            driver.execute_script("arguments[0].click();", element)
            return element
        except (StaleElementReferenceException, WebDriverException):
            time.sleep(0.5)
    raise


def test_jeweldesk_sales_workflow(test_data_fixture, driver):
    """
    Automated Real Browser Test:
    Complete workflow of Logging In, Selecting Inventory, Booking a Sale,
    Verifying Invoice Generation and Inventory Stock Decrement.
    """
    wait = WebDriverWait(driver, 15)

    # =========================================================================
    # STEP 1: Open Local Application and Log In with Dedicated Test Account
    # =========================================================================
    login_url = f"{BASE_URL}/accounts/login/"
    driver.get(login_url)

    # Actual DOM Selectors from accounts/templates/accounts/login.html:
    # Form: #jd-login-form
    # Username Input: #id_username
    # Password Input: #id_password
    # Submit Button: #jd-login-submit-btn
    wait.until(EC.visibility_of_element_located((By.ID, "jd-login-form")))
    time.sleep(1)  # Allow initial autofocus and theme engine to settle

    safe_type(driver, By.ID, "id_username", TEST_USERNAME)
    safe_type(driver, By.ID, "id_password", TEST_PASSWORD)
    safe_click(driver, By.ID, "jd-login-submit-btn")

    # Verify successful authentication redirect away from login page
    wait.until(lambda d: "/accounts/login/" not in d.current_url)
    assert "/dashboard/" in driver.current_url or driver.current_url.endswith("/"), (
        f"Login redirect failed. Current URL is: {driver.current_url}"
    )

    # =========================================================================
    # STEP 2: Navigate to Inventory and Verify Available Test Jewellery Item
    # =========================================================================
    inventory_url = f"{BASE_URL}/inventory/"
    driver.get(inventory_url)

    # Actual DOM Selectors from inventory/templates/inventory/item_list.html:
    # Inventory Table: table.jd-inv-table
    # Item row link: Link text matches item name
    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".jd-inv-table")))

    # Locate and click on the test item in the inventory list
    item_name = test_data_fixture['item'].name
    safe_click(driver, By.LINK_TEXT, item_name)

    # Actual DOM Selectors from inventory/templates/inventory/item_detail.html:
    # Container: .jd-inv-canvas
    # Status Badge: .jd-status-pill
    # Create Bill CTA Button: partial link text 'Create Sale Bill' (href: /sales/add/?item=<id>)
    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".jd-inv-canvas")))
    status_pill_before = driver.find_element(By.CSS_SELECTOR, ".jd-status-pill")
    
    # Verify the item is currently available in stock
    assert "Available" in status_pill_before.text, (
        f"Expected item status to be 'Available', but found '{status_pill_before.text}'"
    )

    # Click '+ Create Sale Bill' to launch the POS billing terminal
    safe_click(driver, By.PARTIAL_LINK_TEXT, "Create Sale Bill")

    # =========================================================================
    # STEP 3: Populate Sales POS Form and Select Test Customer
    # =========================================================================
    # Actual DOM Selectors from sales/templates/sales/sale_form.html:
    # POS Form: #jdPosForm
    # Customer Search Input: #customerSearchInput
    # Selected Customer Dynamic Card: #selectedCustomerCard
    # Customer Card Display Name: #custCardName
    # Complete Sale Submit Button: #btnCompleteSale
    wait.until(EC.visibility_of_element_located((By.ID, "jdPosForm")))
    assert "/sales/add/" in driver.current_url

    # Type customer name into the fast search autocomplete box
    safe_type(driver, By.ID, "customerSearchInput", TEST_CUSTOMER_NAME)
    time.sleep(1)  # Allow POS client-side engine to match and bind selection

    # Verify that the customer card shows the selected customer
    card_customer_name = driver.find_element(By.ID, "custCardName").text
    assert TEST_CUSTOMER_NAME in card_customer_name, (
        f"Customer card was not populated correctly. Displayed: '{card_customer_name}'"
    )

    # =========================================================================
    # STEP 4: Complete and Submit the Sale Transaction
    # =========================================================================
    safe_click(driver, By.ID, "btnCompleteSale")

    # =========================================================================
    # STEP 5: Verify Sale Confirmation & Saved Transaction (Invoice Document)
    # =========================================================================
    # Actual DOM Selectors from sales/templates/sales/sale_detail.html:
    # Redirected URL format: /sales/<sale_id>/
    # Invoice Document Container: #invoice-document
    # Print Receipt Button: #btnPrintReceipt
    wait.until(lambda d: "/sales/" in d.current_url and not d.current_url.endswith("/sales/add/"))
    assert "/sales/" in driver.current_url, (
        f"Expected redirect to sale receipt, got: {driver.current_url}"
    )

    invoice_sheet = wait.until(EC.visibility_of_element_located((By.ID, "invoice-document")))
    invoice_content = invoice_sheet.text

    # Verify customer and jewellery item details are rendered on the official receipt
    assert TEST_CUSTOMER_NAME in invoice_content, (
        f"Invoice receipt does not contain customer '{TEST_CUSTOMER_NAME}'"
    )
    assert item_name in invoice_content, (
        f"Invoice receipt does not contain jewellery item '{item_name}'"
    )
    assert "INV-" in invoice_content, "Invoice number prefix 'INV-' not found on receipt"

    # Verify Print Receipt button exists on page
    print_btn = driver.find_element(By.ID, "btnPrintReceipt")
    assert print_btn.is_displayed(), "Print Receipt button is not displayed on confirmation page"

    # Verify saved sale record in database
    saved_sale = Sale.objects.filter(
        jewellery_item=test_data_fixture['item'],
        customer=test_data_fixture['customer']
    ).order_by('-id').first()
    assert saved_sale is not None, "Sale transaction was not found in the database!"
    assert saved_sale.payment_status in ('Unpaid', 'Paid'), f"Unexpected payment status: {saved_sale.payment_status}"
    assert saved_sale.payment_method == 'Cash', f"Expected Cash payment method, got {saved_sale.payment_method}"

    # =========================================================================
    # STEP 6: Verify Inventory Status Transition (Actual Application Business Logic)
    # =========================================================================
    # When a sale is completed, stock.record_sale() reduces quantity to 0 and marks status as 'Sold'.
    # Navigate back to the inventory item page to verify the updated status.
    driver.get(f"{BASE_URL}/inventory/{test_data_fixture['item'].id}/")
    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".jd-inv-canvas")))

    status_pill_after = driver.find_element(By.CSS_SELECTOR, ".jd-status-pill")
    assert "Sold" in status_pill_after.text, (
        f"Business rule violation: Inventory item status did not update to 'Sold'! Found: '{status_pill_after.text}'"
    )

    # Also verify database state directly
    test_data_fixture['item'].refresh_from_db()
    assert test_data_fixture['item'].status == 'Sold', (
        f"Database status mismatch: Expected 'Sold', got '{test_data_fixture['item'].status}'"
    )
    assert test_data_fixture['item'].quantity == 0, (
        f"Database quantity mismatch: Expected 0, got {test_data_fixture['item'].quantity}"
    )
