"""
outstation/tests.py
-------------------
Comprehensive test suite for Outstation Jewellery Sales & Stock Tracking.
Covers:
- Trip creation, numbering, and tenant isolation
- Tagged jewellery stock issuance, reservation, and prevention of double-issuance
- B2B & B2C sales recording, payment collection, and outstanding balances
- Unsold stock return, showroom availability restoration, and audit movement logs
- Damaged and missing item discrepancies, authorizations, and resolutions
- Strict cross-tenant isolation on models, queries, forms, and views
- Trip closing validation and reports/manifest exports
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, CompanySettings
from customers.models import Customer
from inventory.models import Category, JewelleryItem, StockMovement
from sales.models import Sale, Payment
from team.models import Role, Employee

from .models import (
    OutstationTrip,
    OutstationTripItem,
    OutstationTripSale,
    OutstationTripAuditLog,
    Exhibition,
    ExhibitionExpense,
    ExhibitionItem,
    ExhibitionSale,
    ExhibitionAuditLog,
)
from . import services

User = get_user_model()


class OutstationBaseTestCase(TestCase):
    """Base setup with two distinct tenants, users, employees, and inventory items."""

    def setUp(self):
        # 1. Tenant A (Mahalaxmi Jewellers)
        self.owner_a = User.objects.create_user(
            username='owner_a', email='owner_a@mahalaxmi.test', password='Password123!'
        )
        self.tenant_a = Tenant.objects.create(
            name='Mahalaxmi Jewellers', slug='mahalaxmi', owner=self.owner_a, is_active=True
        )
        self.company_a = CompanySettings.load(tenant=self.tenant_a)
        self.company_a.company_name = 'Mahalaxmi Jewellers Showroom'
        self.company_a.gstin = '07AAAAA0000A1Z5'
        self.company_a.address = 'Gurgaon, Haryana'
        self.company_a.save()

        self.role_mgr, _ = Role.objects.get_or_create(
            name='Manager', defaults={'description': 'Store Manager', 'is_builtin': True}
        )
        self.emp_a1 = Employee.objects.create(
            user=self.owner_a,
            tenant=self.tenant_a,
            employee_id='EMP-A001',
            full_name='Rajesh Soni',
            email='owner_a@mahalaxmi.test',
            role=self.role_mgr,
            status='Active'
        )

        self.staff_user_a = User.objects.create_user(
            username='staff_a', email='staff_a@mahalaxmi.test', password='Password123!'
        )
        self.emp_a2 = Employee.objects.create(
            user=self.staff_user_a,
            tenant=self.tenant_a,
            employee_id='EMP-A002',
            full_name='Sunil Verma',
            email='staff_a@mahalaxmi.test',
            role=self.role_mgr,
            status='Active'
        )

        self.cat_a = Category.objects.create(tenant=self.tenant_a, name='Bangles')
        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a, name='Anita Sharma', mobile='9811122233'
        )

        # Inventory for Tenant A
        self.item_a1 = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            item_code='BNG-001',
            tag_number='JWL-001001',
            name='22K Heritage Kada',
            category=self.cat_a,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('25.500'),
            net_weight=Decimal('24.800'),
            selling_price=Decimal('185000.00'),
            status='Available',
            quantity=1
        )

        self.item_a2 = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            item_code='BNG-002',
            tag_number='JWL-001002',
            name='22K Antique Churi',
            category=self.cat_a,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('18.200'),
            net_weight=Decimal('18.000'),
            selling_price=Decimal('135000.00'),
            status='Available',
            quantity=1
        )

        # 2. Tenant B (Kalyan Jewellers)
        self.owner_b = User.objects.create_user(
            username='owner_b', email='owner_b@kalyan.test', password='Password123!'
        )
        self.tenant_b = Tenant.objects.create(
            name='Kalyan Jewellers', slug='kalyan', owner=self.owner_b, is_active=True
        )
        self.emp_b1 = Employee.objects.create(
            user=self.owner_b,
            tenant=self.tenant_b,
            employee_id='EMP-B001',
            full_name='Kalyan Kumar',
            email='owner_b@kalyan.test',
            role=self.role_mgr,
            status='Active'
        )
        self.cat_b = Category.objects.create(tenant=self.tenant_b, name='Chains')
        self.customer_b = Customer.objects.create(
            tenant=self.tenant_b, name='Suresh Patel', mobile='9899988877'
        )
        self.item_b1 = JewelleryItem.objects.create(
            tenant=self.tenant_b,
            item_code='CHN-001',
            tag_number='JWL-002001',
            name='22K Dubai Rope Chain',
            category=self.cat_b,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('30.000'),
            net_weight=Decimal('30.000'),
            selling_price=Decimal('220000.00'),
            status='Available',
            quantity=1
        )

        # Clients
        self.client_a = Client()
        self.client_a.login(username='owner_a', password='Password123!')

        self.client_b = Client()
        self.client_b.login(username='owner_b', password='Password123!')


class OutstationTripManagementTests(OutstationBaseTestCase):
    """Tests for trip creation, sequential numbering, and validation."""

    def test_trip_creation_and_auto_numbering(self):
        """Verify automatic sequential trip numbering formatted as TRIP-YYYY-NNNN."""
        year = timezone.now().year
        trip1 = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            destination_location='Gold Souk Mall',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=3),
            responsible_employee=self.emp_a2,
            created_by=self.owner_a
        )
        self.assertEqual(trip1.trip_number, f"TRIP-{year}-0001")
        self.assertEqual(trip1.status, OutstationTrip.STATUS_DRAFT)

        trip2 = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Delhi',
            destination_location='Karol Bagh',
            departure_date=timezone.now().date() + timedelta(days=5),
            expected_return_date=timezone.now().date() + timedelta(days=8),
            responsible_employee=self.emp_a2,
            created_by=self.owner_a
        )
        self.assertEqual(trip2.trip_number, f"TRIP-{year}-0002")

    def test_tenant_independent_trip_sequences(self):
        """Verify that Tenant A and Tenant B have separate trip numbering spaces."""
        year = timezone.now().year
        trip_a = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a1,
        )
        trip_b = OutstationTrip.objects.create(
            tenant=self.tenant_b,
            destination_city='Jaipur',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_b1,
        )
        self.assertEqual(trip_a.trip_number, f"TRIP-{year}-0001")
        self.assertEqual(trip_b.trip_number, f"TRIP-{year}-0001")


class OutstationStockIssuanceTests(OutstationBaseTestCase):
    """Tests for selecting, locking, and issuing jewellery stock to trips."""

    def setUp(self):
        super().setUp()
        self.trip = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Delhi',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a2,
            created_by=self.owner_a
        )

    def test_issue_items_successfully_reserves_stock(self):
        """Issuing items must set their status to Reserved and create traceable StockMovements."""
        count = services.issue_items_to_trip(
            trip=self.trip,
            item_ids=[self.item_a1.id, self.item_a2.id],
            user=self.owner_a
        )
        self.assertEqual(count, 2)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, OutstationTrip.STATUS_ISSUED)
        self.assertEqual(self.trip.total_items_count, 2)

        # Items are now Reserved and excluded from showroom available stock
        self.item_a1.refresh_from_db()
        self.item_a2.refresh_from_db()
        self.assertEqual(self.item_a1.status, 'Reserved')
        self.assertEqual(self.item_a2.status, 'Reserved')

        # Verify OutstationTripItem snapshots
        ti1 = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a1)
        self.assertEqual(ti1.issue_price, Decimal('185000.00'))
        self.assertEqual(ti1.issue_gross_weight, Decimal('25.500'))
        self.assertEqual(ti1.status, OutstationTripItem.STATUS_ISSUED)

        # Verify OutstationTripAuditLog
        audit_logs = OutstationTripAuditLog.objects.filter(trip=self.trip, action=OutstationTripAuditLog.ACTION_STOCK_ISSUED)
        self.assertTrue(audit_logs.exists())

    def test_prevent_duplicate_issuance_to_two_active_trips(self):
        """A piece already issued to Trip 1 cannot be issued to Trip 2."""
        services.issue_items_to_trip(self.trip, [self.item_a1.id], user=self.owner_a)

        trip2 = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a1,
        )

        with self.assertRaises(ValidationError) as ctx:
            services.issue_items_to_trip(trip2, [self.item_a1.id], user=self.owner_a)
        self.assertIn("already issued to an active trip", str(ctx.exception))

    def test_prevent_issuing_sold_items(self):
        """Items marked 'Sold' must not be eligible for trip issuance."""
        self.item_a1.status = 'Sold'
        self.item_a1.save()

        with self.assertRaises(ValidationError) as ctx:
            services.issue_items_to_trip(self.trip, [self.item_a1.id], user=self.owner_a)
        self.assertIn("is not available", str(ctx.exception))


class OutstationSalesAndPaymentsTests(OutstationBaseTestCase):
    """Tests for recording B2B wholesale and B2C retail sales on trips."""

    def setUp(self):
        super().setUp()
        self.trip = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a2,
            created_by=self.owner_a
        )
        services.issue_items_to_trip(
            self.trip, [self.item_a1.id, self.item_a2.id], user=self.owner_a
        )

    def test_record_b2b_wholesale_sale_with_full_payment(self):
        """B2B sale records business name, GSTIN, marks item as Sold, and records payment."""
        sale = services.record_outstation_sale(
            trip=self.trip,
            item_id=self.item_a1.id,
            customer=self.customer_a,
            sale_price=Decimal('180000.00'),
            payment_method='Bank Transfer',
            buyer_type='B2B',
            business_name='Gurgaon Bullion & Jewellers',
            business_gstin='06ABCDE1234F1Z5',
            notes='Wholesale trade delivery',
            user=self.owner_a,
            paid_amount=Decimal('180000.00'),
            payment_ref='NEFT-788990'
        )

        self.assertIsNotNone(sale)
        self.assertEqual(sale.sale_price, Decimal('180000.00'))
        self.assertEqual(sale.payment_status, 'Paid')

        # Check trip item status
        ti = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a1)
        self.assertEqual(ti.status, OutstationTripItem.STATUS_SOLD)

        # Check item status is Sold
        self.item_a1.refresh_from_db()
        self.assertEqual(self.item_a1.status, 'Sold')

        # Check OutstationTripSale link
        trip_sale = OutstationTripSale.objects.get(sale=sale)
        self.assertEqual(trip_sale.buyer_type, 'B2B')
        self.assertEqual(trip_sale.business_name, 'Gurgaon Bullion & Jewellers')
        self.assertEqual(trip_sale.business_gstin, '06ABCDE1234F1Z5')

        # Trip status is updated to In Progress
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, OutstationTrip.STATUS_IN_PROGRESS)
        self.assertEqual(self.trip.sold_items_count, 1)
        self.assertEqual(self.trip.in_transit_items_count, 1)
        self.assertEqual(self.trip.total_sales_amount, Decimal('180000.00'))
        self.assertEqual(self.trip.outstanding_balance, Decimal('0.00'))

    def test_record_b2c_sale_with_partial_payment(self):
        """B2C sale with partial payment computes outstanding balance accurately."""
        sale = services.record_outstation_sale(
            trip=self.trip,
            item_id=self.item_a2.id,
            customer=self.customer_a,
            sale_price=Decimal('135000.00'),
            payment_method='UPI',
            buyer_type='B2C',
            user=self.owner_a,
            paid_amount=Decimal('50000.00'),
            payment_ref='UPI-899123'
        )

        self.assertEqual(sale.payment_status, 'Partially Paid')
        self.assertEqual(sale.paid_amount, Decimal('50000.00'))

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.total_sales_amount, Decimal('135000.00'))
        self.assertEqual(self.trip.total_collected_amount, Decimal('50000.00'))
        self.assertEqual(self.trip.outstanding_balance, Decimal('85000.00'))

    def test_prevent_selling_unissued_or_already_sold_item(self):
        """Cannot sell an item that has already been sold on the trip."""
        services.record_outstation_sale(
            trip=self.trip,
            item_id=self.item_a1.id,
            customer=self.customer_a,
            sale_price=Decimal('185000.00'),
            payment_method='Cash',
            user=self.owner_a
        )

        with self.assertRaises(ValidationError) as ctx:
            services.record_outstation_sale(
                trip=self.trip,
                item_id=self.item_a1.id,
                customer=self.customer_a,
                sale_price=Decimal('185000.00'),
                payment_method='Cash',
                user=self.owner_a
            )
        self.assertIn("not currently in transit", str(ctx.exception))


class OutstationReturnsAndReconciliationTests(OutstationBaseTestCase):
    """Tests for returning unsold stock to showroom, handling damage/missing discrepancies, and closing trips."""

    def setUp(self):
        super().setUp()
        self.trip = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a2,
            created_by=self.owner_a
        )
        services.issue_items_to_trip(
            self.trip, [self.item_a1.id, self.item_a2.id], user=self.owner_a
        )

    def test_return_unsold_item_restores_showroom_stock(self):
        """Returning unsold piece must transition status back to 'Available' in showroom stock."""
        ti = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a1)

        services.reconcile_trip_item(
            trip_item=ti,
            outcome=OutstationTripItem.STATUS_RETURNED,
            notes='Returned in pristine condition',
            user=self.owner_a
        )

        ti.refresh_from_db()
        self.assertEqual(ti.status, OutstationTripItem.STATUS_RETURNED)
        self.assertIsNotNone(ti.reconciled_at)
        self.assertEqual(ti.reconciled_by, self.owner_a)

        # JewelleryItem must now be Available again for counter sales
        self.item_a1.refresh_from_db()
        self.assertEqual(self.item_a1.status, 'Available')

        # OutstationTripAuditLog recorded
        audit_logs = OutstationTripAuditLog.objects.filter(
            trip=self.trip, action=OutstationTripAuditLog.ACTION_STOCK_RETURNED
        )
        self.assertTrue(audit_logs.exists())

    def test_cannot_return_already_sold_item(self):
        """An item marked 'Sold' cannot be returned as available stock via trip reconciliation."""
        services.record_outstation_sale(
            trip=self.trip,
            item_id=self.item_a1.id,
            customer=self.customer_a,
            sale_price=Decimal('185000.00'),
            payment_method='Cash',
            user=self.owner_a
        )
        ti = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a1)

        with self.assertRaises(ValidationError) as ctx:
            services.reconcile_trip_item(
                trip_item=ti,
                outcome=OutstationTripItem.STATUS_RETURNED,
                user=self.owner_a
            )
        self.assertIn("already been sold", str(ctx.exception))

    def test_damaged_missing_item_requires_reason(self):
        """Marking an item Damaged or Missing without a reason must fail."""
        ti = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a2)

        with self.assertRaises(ValidationError) as ctx:
            services.reconcile_trip_item(
                trip_item=ti,
                outcome=OutstationTripItem.STATUS_DAMAGED,
                discrepancy_reason='',  # Missing reason
                user=self.owner_a
            )
        self.assertIn("Discrepancy explanation reason", str(ctx.exception))

    def test_damaged_item_resolution_and_stock_write_off(self):
        """Reporting damage and subsequent manager authorization with write-off."""
        ti = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a2)
        services.reconcile_trip_item(
            trip_item=ti,
            outcome=OutstationTripItem.STATUS_DAMAGED,
            discrepancy_reason='Clasp snapped during exhibition display',
            user=self.owner_a
        )

        ti.refresh_from_db()
        self.assertEqual(ti.status, OutstationTripItem.STATUS_DAMAGED)
        self.assertFalse(ti.discrepancy_resolved)

        # Resolve discrepancy
        services.resolve_item_discrepancy(
            trip_item=ti,
            resolution_notes='Written off for repair and remelt in workshop',
            write_off_stock=True,
            user=self.owner_a
        )

        ti.refresh_from_db()
        self.assertTrue(ti.discrepancy_resolved)
        self.assertEqual(ti.discrepancy_resolved_by, self.owner_a)

        # Stock quantity written off
        self.item_a2.refresh_from_db()
        self.assertEqual(self.item_a2.quantity, 0)

    def test_prevent_closing_trip_with_in_transit_items(self):
        """Cannot close a trip while items remain unreconciled in transit."""
        # 1 item returned, 1 still in transit
        ti1 = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a1)
        services.reconcile_trip_item(
            trip_item=ti1, outcome=OutstationTripItem.STATUS_RETURNED, user=self.owner_a
        )

        with self.assertRaises(ValidationError) as ctx:
            services.close_outstation_trip(self.trip, user=self.owner_a)
        self.assertIn("still recorded as in-transit", str(ctx.exception))

    def test_prevent_closing_trip_with_unresolved_discrepancy(self):
        """Cannot close a trip if an item was reported damaged/missing but not officially resolved."""
        ti1 = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a1)
        services.reconcile_trip_item(
            trip_item=ti1, outcome=OutstationTripItem.STATUS_RETURNED, user=self.owner_a
        )

        ti2 = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a2)
        services.reconcile_trip_item(
            trip_item=ti2,
            outcome=OutstationTripItem.STATUS_MISSING,
            discrepancy_reason='Sample piece lost in transit',
            user=self.owner_a
        )

        with self.assertRaises(ValidationError) as ctx:
            services.close_outstation_trip(self.trip, user=self.owner_a)
        self.assertIn("requires manager resolution", str(ctx.exception))

    def test_successful_trip_closure_when_all_accounted(self):
        """When all pieces are reconciled and resolved, trip closes successfully."""
        ti1 = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a1)
        services.reconcile_trip_item(
            trip_item=ti1, outcome=OutstationTripItem.STATUS_RETURNED, user=self.owner_a
        )

        ti2 = OutstationTripItem.objects.get(trip=self.trip, item=self.item_a2)
        services.reconcile_trip_item(
            trip_item=ti2,
            outcome=OutstationTripItem.STATUS_MISSING,
            discrepancy_reason='Sample lost',
            user=self.owner_a
        )
        services.resolve_item_discrepancy(
            trip_item=ti2,
            resolution_notes='Claim settled with carrier',
            write_off_stock=True,
            user=self.owner_a
        )

        trip_closed = services.close_outstation_trip(
            self.trip, user=self.owner_a, actual_return_date=timezone.now().date()
        )
        self.assertEqual(trip_closed.status, OutstationTrip.STATUS_CLOSED)
        self.assertEqual(trip_closed.actual_return_date, timezone.now().date())


class OutstationTenantIsolationSecurityTests(OutstationBaseTestCase):
    """Rigorous security tests verifying multi-tenant boundary enforcement."""

    def setUp(self):
        super().setUp()
        self.trip_a = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        self.trip_b = OutstationTrip.objects.create(
            tenant=self.tenant_b,
            destination_city='Mumbai',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_b1,
            created_by=self.owner_b
        )

    def test_tenant_cannot_view_other_tenant_trips_in_list(self):
        """Tenant A's trip list must never display Tenant B's trips."""
        res_a = self.client_a.get(reverse('outstation:trip_list'))
        self.assertEqual(res_a.status_code, 200)
        self.assertContains(res_a, 'Gurgaon')
        self.assertNotContains(res_a, 'Mumbai')

        res_b = self.client_b.get(reverse('outstation:trip_list'))
        self.assertEqual(res_b.status_code, 200)
        self.assertContains(res_b, 'Mumbai')
        self.assertNotContains(res_b, 'Gurgaon')

    def test_cross_tenant_trip_detail_access_blocked(self):
        """Attempting to access Tenant B's trip by changing ID in URL returns 404."""
        response = self.client_a.get(reverse('outstation:trip_detail', kwargs={'pk': self.trip_b.pk}))
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_trip_edit_access_blocked(self):
        """Attempting to edit Tenant B's trip returns 404."""
        response = self.client_a.get(reverse('outstation:trip_edit', kwargs={'pk': self.trip_b.pk}))
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_stock_issuance_blocked(self):
        """Tenant A cannot issue Tenant B's jewellery item to Tenant A's trip."""
        response = self.client_a.post(
            reverse('outstation:trip_issue_stock', kwargs={'pk': self.trip_a.pk}),
            {'selected_items': [self.item_b1.id]},
            follow=True
        )
        # Should result in error message and 0 items issued
        self.item_b1.refresh_from_db()
        self.assertEqual(self.item_b1.status, 'Available')
        self.assertEqual(self.trip_a.issued_items.count(), 0)

    def test_cross_tenant_stock_sheet_blocked(self):
        """Tenant A cannot view or print Tenant B's custody stock sheet."""
        response = self.client_a.get(reverse('outstation:trip_stock_sheet', kwargs={'pk': self.trip_b.pk}))
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_csv_export_blocked(self):
        """Tenant A cannot export Tenant B's trip CSV manifest."""
        response = self.client_a.get(reverse('outstation:trip_export_csv', kwargs={'pk': self.trip_b.pk}))
        self.assertEqual(response.status_code, 404)


class OutstationReportsAndExportsTests(OutstationBaseTestCase):
    """Tests for UI rendering, printable stock sheets, and CSV exports."""

    def setUp(self):
        super().setUp()
        self.trip = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        services.issue_items_to_trip(self.trip, [self.item_a1.id], user=self.owner_a)

    def test_printable_stock_sheet_contains_mandated_fields(self):
        """Stock sheet displays showroom info, tags, weights, and legal custody undertaking."""
        response = self.client_a.get(reverse('outstation:trip_stock_sheet', kwargs={'pk': self.trip.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mahalaxmi Jewellers Showroom')
        self.assertContains(response, self.item_a1.tag_number)
        self.assertContains(response, 'CUSTODY &amp; RESPONSIBILITY UNDERTAKING')
        self.assertContains(response, self.emp_a1.full_name)

    def test_csv_manifest_export_download(self):
        """CSV export returns proper attachment header and item row data."""
        response = self.client_a.get(reverse('outstation:trip_export_csv', kwargs={'pk': self.trip.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn(f'outstation_manifest_{self.trip.trip_number}.csv', response['Content-Disposition'])

        content = response.content.decode('utf-8')
        self.assertIn('Tag Number,Item Code,Item Name', content)
        self.assertIn(self.item_a1.tag_number, content)
        self.assertIn('22K Heritage Kada', content)


# ==============================================================================
# EXHIBITION TEST SUITES
# ==============================================================================

class ExhibitionModelAndNumberingTests(OutstationBaseTestCase):
    """Tests for Exhibition creation, sequence numbering, and aggregated calculations."""

    def test_auto_exhibition_number_generation(self):
        """Exhibition number follows EXH-YYYY-0001 pattern."""
        exh = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='IIJS Premiere 2026',
            venue='Jio World Convention Centre',
            city='Mumbai',
            stall_number='Booth 1A-24',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=4),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        year = timezone.now().year
        self.assertEqual(exh.exhibition_number, f"EXH-{year}-0001")

        # Second exhibition should be EXH-YYYY-0002
        exh2 = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='Delhi Jewellery Show',
            venue='Pragati Maidan',
            city='New Delhi',
            stall_number='Hall 5, Stall 12',
            start_date=timezone.now().date() + timedelta(days=10),
            end_date=timezone.now().date() + timedelta(days=13),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        self.assertEqual(exh2.exhibition_number, f"EXH-{year}-0002")

    def test_tenant_isolation_in_exhibition_numbering(self):
        """Each tenant starts their own exhibition numbering sequence at EXH-YYYY-0001."""
        year = timezone.now().year
        exh_a = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='Tenant A Fair',
            venue='Venue A',
            city='Mumbai',
            stall_number='Stall A1',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        exh_b = Exhibition.objects.create(
            tenant=self.tenant_b,
            name='Tenant B Fair',
            venue='Venue B',
            city='Delhi',
            stall_number='Stall B1',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_b1,
            created_by=self.owner_b
        )
        self.assertEqual(exh_a.exhibition_number, f"EXH-{year}-0001")
        self.assertEqual(exh_b.exhibition_number, f"EXH-{year}-0001")


class ExhibitionStockIssuanceAndMutualExclusionTests(OutstationBaseTestCase):
    """Tests for stock issuance and cross-feature mutual exclusion between Trips and Exhibitions."""

    def setUp(self):
        super().setUp()
        self.exhibition = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='Sparkle Surat Expo',
            venue='Surat International Exhibition Centre',
            city='Surat',
            stall_number='Booth S-10',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=3),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        self.trip = OutstationTrip.objects.create(
            tenant=self.tenant_a,
            destination_city='Gurgaon',
            departure_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )

    def test_successful_stock_issuance_to_exhibition(self):
        """Issuing items reserves them and creates ExhibitionItem records."""
        count = services.issue_items_to_exhibition(
            self.exhibition, [self.item_a1.id, self.item_a2.id], user=self.owner_a
        )
        self.assertEqual(count, 2)
        self.item_a1.refresh_from_db()
        self.item_a2.refresh_from_db()
        self.exhibition.refresh_from_db()
        self.assertEqual(self.item_a1.status, 'Reserved')
        self.assertEqual(self.item_a2.status, 'Reserved')
        self.assertEqual(self.exhibition.issued_items.count(), 2)
        self.assertEqual(self.exhibition.status, Exhibition.STATUS_ISSUED)

    def test_cannot_issue_already_exhibition_issued_item_to_another_exhibition(self):
        """An item issued to Exhibition 1 cannot be issued to Exhibition 2."""
        services.issue_items_to_exhibition(self.exhibition, [self.item_a1.id], user=self.owner_a)

        exh2 = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='Second Expo',
            venue='JWCC',
            city='Mumbai',
            stall_number='Booth 42',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=3),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        with self.assertRaises(ValidationError) as ctx:
            services.issue_items_to_exhibition(exh2, [self.item_a1.id], user=self.owner_a)
        self.assertIn('already issued to an active exhibition', str(ctx.exception).lower())

    def test_cross_feature_mutual_exclusion_exhibition_to_trip(self):
        """Piece issued to Exhibition CANNOT be issued to Outstation Trip."""
        services.issue_items_to_exhibition(self.exhibition, [self.item_a1.id], user=self.owner_a)

        with self.assertRaises(ValidationError) as ctx:
            services.issue_items_to_trip(self.trip, [self.item_a1.id], user=self.owner_a)
        self.assertIn('already issued to an active exhibition', str(ctx.exception).lower())

    def test_cross_feature_mutual_exclusion_trip_to_exhibition(self):
        """Piece issued to Outstation Trip CANNOT be issued to Exhibition."""
        services.issue_items_to_trip(self.trip, [self.item_a1.id], user=self.owner_a)

        with self.assertRaises(ValidationError) as ctx:
            services.issue_items_to_exhibition(self.exhibition, [self.item_a1.id], user=self.owner_a)
        self.assertIn('already issued to an active outstation trip', str(ctx.exception).lower())


class ExhibitionSalesAndExpensesTests(OutstationBaseTestCase):
    """Tests for on-site exhibition sales (B2B & B2C), payment tracking, and expenses."""

    def setUp(self):
        super().setUp()
        self.exhibition = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='IIJS Signature',
            venue='Bombay Exhibition Centre',
            city='Mumbai',
            stall_number='Hall 2, Stall 2B-18',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=3),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        services.issue_items_to_exhibition(self.exhibition, [self.item_a1.id, self.item_a2.id], user=self.owner_a)

    def test_record_b2c_retail_sale(self):
        """Retail B2C sale records sale, creates ExhibitionSale, marks item Sold."""
        sale = services.record_exhibition_sale(
            exhibition=self.exhibition,
            item_id=self.item_a1.id,
            customer=self.customer_a,
            sale_price=Decimal('165000.00'),
            payment_method='UPI',
            buyer_type='B2C',
            user=self.owner_a,
            paid_amount=Decimal('165000.00')
        )
        self.assertIsNotNone(sale)
        self.assertEqual(sale.sale_price, Decimal('165000.00'))

        # Verify ExhibitionItem status
        exh_item = ExhibitionItem.objects.get(exhibition=self.exhibition, item=self.item_a1)
        self.assertEqual(exh_item.status, ExhibitionItem.STATUS_SOLD)

        # Verify JewelleryItem is sold
        self.item_a1.refresh_from_db()
        self.assertEqual(self.item_a1.status, 'Sold')
        self.assertEqual(self.item_a1.quantity, 0)

        # Verify StockMovement created
        movement = StockMovement.objects.filter(item=self.item_a1, movement_type=StockMovement.SALE).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity_change, -1)

    def test_record_b2b_wholesale_sale_with_partial_payment(self):
        """B2B sale stores firm name, GSTIN, and correctly tracks outstanding balance."""
        sale = services.record_exhibition_sale(
            exhibition=self.exhibition,
            item_id=self.item_a2.id,
            customer=self.customer_a,
            sale_price=Decimal('100000.00'),
            payment_method='Bank Transfer',
            buyer_type='B2B',
            business_name='Kalyan Jewellers Partner',
            business_gstin='27ABCDE1234F1Z5',
            user=self.owner_a,
            paid_amount=Decimal('40000.00'),
            payment_ref='NEFT-20261019-99'
        )
        exh_sale = ExhibitionSale.objects.get(sale=sale)
        self.assertEqual(exh_sale.buyer_type, 'B2B')
        self.assertEqual(exh_sale.business_name, 'Kalyan Jewellers Partner')
        self.assertEqual(exh_sale.business_gstin, '27ABCDE1234F1Z5')
        self.assertEqual(sale.paid_amount, Decimal('40000.00'))
        self.exhibition.refresh_from_db()
        self.assertEqual(self.exhibition.outstanding_balance, Decimal('60000.00'))

    def test_record_expenses_and_operating_surplus(self):
        """Expenses are tracked across categories and Operating Surplus is properly computed."""
        # Log stall rent expense
        services.record_exhibition_expense(
            exhibition=self.exhibition,
            category=ExhibitionExpense.CAT_STALL_RENT,
            amount=Decimal('50000.00'),
            payee='GJEPC Council',
            expense_date=self.exhibition.start_date,
            user=self.owner_a
        )
        # Log hotel accommodation expense
        services.record_exhibition_expense(
            exhibition=self.exhibition,
            category=ExhibitionExpense.CAT_ACCOMMODATION,
            amount=Decimal('15000.00'),
            payee='Trident Hotel BKC',
            expense_date=self.exhibition.start_date,
            user=self.owner_a
        )

        self.assertEqual(self.exhibition.total_expenses_amount, Decimal('65000.00'))

        # Record a sale of 165,000
        services.record_exhibition_sale(
            exhibition=self.exhibition,
            item_id=self.item_a1.id,
            customer=self.customer_a,
            sale_price=Decimal('165000.00'),
            payment_method='Cash',
            buyer_type='B2C',
            user=self.owner_a,
            paid_amount=Decimal('165000.00')
        )

        # Operating Surplus = 165000 - 65000 = 100000
        self.assertEqual(self.exhibition.total_sales_amount, Decimal('165000.00'))
        self.assertEqual(self.exhibition.operating_surplus, Decimal('100000.00'))


class ExhibitionReconciliationAndClosureTests(OutstationBaseTestCase):
    """Tests for piece returns, damaged/missing item resolutions, and final exhibition closure safeguards."""

    def setUp(self):
        super().setUp()
        self.exhibition = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='Jaipur Jewellery Show (JJS)',
            venue='JECC Sitapura',
            city='Jaipur',
            stall_number='Hall 3, Stall 3A-12',
            start_date=timezone.now().date() - timedelta(days=3),
            end_date=timezone.now().date(),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        services.issue_items_to_exhibition(self.exhibition, [self.item_a1.id, self.item_a2.id], user=self.owner_a)

    def test_reconcile_item_as_returned_restores_showroom_inventory(self):
        """Reconciling as Returned resets item status to Available and restores quantity."""
        exh_item = ExhibitionItem.objects.get(exhibition=self.exhibition, item=self.item_a1)
        services.reconcile_exhibition_item(
            exhibition_item=exh_item,
            outcome='Returned',
            user=self.owner_a
        )
        exh_item.refresh_from_db()
        self.assertEqual(exh_item.status, ExhibitionItem.STATUS_RETURNED)

        self.item_a1.refresh_from_db()
        self.assertEqual(self.item_a1.status, 'Available')
        self.assertEqual(self.item_a1.quantity, 1)

    def test_damaged_missing_requires_mandatory_explanation(self):
        """Marking piece Damaged or Missing requires an explanation reason."""
        exh_item = ExhibitionItem.objects.get(exhibition=self.exhibition, item=self.item_a1)
        with self.assertRaises(ValidationError):
            services.reconcile_exhibition_item(
                exhibition_item=exh_item,
                outcome='Damaged',
                discrepancy_reason='',
                user=self.owner_a
            )

    def test_closure_blocked_when_items_still_at_booth(self):
        """Cannot close exhibition while pieces are still marked as Issued/At Booth."""
        with self.assertRaises(ValidationError) as ctx:
            services.close_exhibition(self.exhibition, user=self.owner_a)
        self.assertIn('still recorded as in-transit at the booth', str(ctx.exception).lower())

    def test_closure_blocked_when_unresolved_discrepancies_exist(self):
        """Cannot close exhibition with unresolved damaged or missing pieces."""
        exh_item = ExhibitionItem.objects.get(exhibition=self.exhibition, item=self.item_a1)
        services.reconcile_exhibition_item(
            exhibition_item=exh_item,
            outcome='Missing',
            discrepancy_reason='Showcase theft report filed with police',
            user=self.owner_a
        )
        # Return second item
        exh_item2 = ExhibitionItem.objects.get(exhibition=self.exhibition, item=self.item_a2)
        services.reconcile_exhibition_item(
            exhibition_item=exh_item2,
            outcome='Returned',
            user=self.owner_a
        )

        with self.assertRaises(ValidationError) as ctx:
            services.close_exhibition(self.exhibition, user=self.owner_a)
        self.assertIn('requires manager resolution', str(ctx.exception).lower())

    def test_resolve_discrepancy_and_successful_closure(self):
        """Resolving missing piece with inventory write-off allows exhibition to close."""
        exh_item = ExhibitionItem.objects.get(exhibition=self.exhibition, item=self.item_a1)
        services.reconcile_exhibition_item(
            exhibition_item=exh_item,
            outcome='Missing',
            discrepancy_reason='Showcase theft report filed with police',
            user=self.owner_a
        )
        # Return second item
        exh_item2 = ExhibitionItem.objects.get(exhibition=self.exhibition, item=self.item_a2)
        services.reconcile_exhibition_item(
            exhibition_item=exh_item2,
            outcome='Returned',
            user=self.owner_a
        )

        # Authorize and resolve discrepancy
        services.resolve_exhibition_discrepancy(
            exhibition_item=exh_item,
            resolution_notes='FIR filed. Insurance claim #IN-9023 acknowledged. Written off in ledger.',
            write_off_stock=True,
            user=self.owner_a
        )

        # Item should now be written off
        self.item_a1.refresh_from_db()
        self.assertEqual(self.item_a1.quantity, 0)
        self.assertIn(self.item_a1.status, ['Sold', 'Damaged'])

        # Now closing the exhibition must succeed
        closed_exh = services.close_exhibition(
            self.exhibition,
            user=self.owner_a,
            actual_return_date=timezone.now().date(),
            notes='All items reconciled and booth vacated.'
        )
        self.assertEqual(closed_exh.status, Exhibition.STATUS_CLOSED)


class ExhibitionMultiTenantIsolationTests(OutstationBaseTestCase):
    """Tests guaranteeing strict tenant boundaries on exhibition data, views, and stock."""

    def setUp(self):
        super().setUp()
        self.exh_a = Exhibition.objects.create(
            tenant=self.tenant_a,
            name='Tenant A Exhibition',
            venue='Jio World',
            city='Mumbai',
            stall_number='Stall A1',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_a1,
            created_by=self.owner_a
        )
        self.exh_b = Exhibition.objects.create(
            tenant=self.tenant_b,
            name='Tenant B Exhibition',
            venue='Pragati Maidan',
            city='New Delhi',
            stall_number='Stall B1',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=2),
            responsible_employee=self.emp_b1,
            created_by=self.owner_b
        )

    def test_tenant_a_cannot_view_tenant_b_exhibitions(self):
        """Exhibition list filters strictly by tenant."""
        response = self.client_a.get(reverse('outstation:exhibition_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tenant A Exhibition')
        self.assertNotContains(response, 'Tenant B Exhibition')

    def test_tenant_a_cannot_access_tenant_b_exhibition_detail(self):
        """Detail view returns 404 when querying an exhibition owned by another showroom."""
        response = self.client_a.get(reverse('outstation:exhibition_detail', kwargs={'pk': self.exh_b.pk}))
        self.assertEqual(response.status_code, 404)

    def test_tenant_a_cannot_issue_tenant_b_jewellery_to_exhibition(self):
        """Stock issuance validates item tenant ownership and rejects cross-tenant pieces."""
        with self.assertRaises(ValidationError) as ctx:
            services.issue_items_to_exhibition(self.exh_a, [self.item_b1.id], user=self.owner_a)
        self.assertIn('do not belong to this showroom', str(ctx.exception).lower())

    def test_cross_tenant_stock_sheet_and_csv_blocked(self):
        """Printable stock sheets and CSV downloads reject cross-tenant requests with 404."""
        response_sheet = self.client_a.get(reverse('outstation:exhibition_stock_sheet', kwargs={'pk': self.exh_b.pk}))
        self.assertEqual(response_sheet.status_code, 404)

        response_csv = self.client_a.get(reverse('outstation:exhibition_export_csv', kwargs={'pk': self.exh_b.pk}))
        self.assertEqual(response_csv.status_code, 404)


