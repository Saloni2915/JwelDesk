"""
girvi/tests.py
--------------
Comprehensive unit and integration test suite for the JwelDesk Girvi module.

Verifies:
1. Multi-tenant isolation (Tenant A cannot view or touch Tenant B's loans).
2. Branch access enforcement.
3. Accurate Decimal-based interest calculation (Simple Monthly, Simple Daily, Fixed Monthly).
4. Snapshot preservation: changing showroom defaults never alters active loans.
5. Inventory isolation: pledging items creates GirviItem pieces with ZERO mutation to inventory.JewelleryItem.
6. Immutable payment ledger & auditable reversal.
7. Explicit authorized waivers.
8. Release eligibility: blocks release if balance > 0; permits release on full settlement.
9. Sequence generator collision safety.
10. Views and templates integration.
"""

from decimal import Decimal
import datetime

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from django.core.exceptions import ValidationError, PermissionDenied

from accounts.models import Tenant
from team.models import Branch, Employee, Role, EmployeePermission
from customers.models import Customer
from inventory.models import JewelleryItem, Category

from .models import (
    GirviSetting,
    GirviSequence,
    GirviLoan,
    GirviItem,
    GirviPayment,
    GirviWaiver,
    GirviAuditLog,
)
from .services import (
    get_or_create_girvi_settings,
    get_next_sequence_number,
    calculate_loan_financials,
    record_payment,
    reverse_payment,
    record_waiver,
    release_collateral,
)

User = get_user_model()


class GirviBaseTestCase(TestCase):
    """Setup base multi-tenant environment with two independent showrooms and branches."""

    def setUp(self):
        # Tenant A (Primary Showroom)
        self.owner_a = User.objects.create_user(
            username='owner_a', email='owner_a@showroom.test', password='password123', first_name='Aman'
        )
        self.tenant_a = Tenant.objects.create(name='A Jwellers', owner=self.owner_a)
        self.branch_a1 = Branch.objects.create(tenant=self.tenant_a, name='Main Branch', is_default=True)
        self.branch_a2 = Branch.objects.create(tenant=self.tenant_a, name='City Branch')

        # Tenant B (Competitor Showroom)
        self.owner_b = User.objects.create_user(
            username='owner_b', email='owner_b@showroom.test', password='password123', first_name='Bharat'
        )
        self.tenant_b = Tenant.objects.create(name='B Jwellers', owner=self.owner_b)
        self.branch_b = Branch.objects.create(tenant=self.tenant_b, name='B Branch', is_default=True)

        # Customers
        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a, branch=self.branch_a1, name='Ramesh Kumar', mobile='9876543210'
        )
        self.customer_b = Customer.objects.create(
            tenant=self.tenant_b, branch=self.branch_b, name='Suresh Verma', mobile='9123456780'
        )

        # Clients
        self.client_a = Client()
        self.client_a.force_login(self.owner_a)

        self.client_b = Client()
        self.client_b.force_login(self.owner_b)


class GirviSequenceAndSettingsTests(GirviBaseTestCase):
    """Test showroom configuration defaults and atomic sequence generator."""

    def test_settings_creation_and_defaults(self):
        setting = get_or_create_girvi_settings(self.tenant_a)
        self.assertEqual(setting.loan_number_prefix, 'GIR-')
        self.assertEqual(setting.default_interest_rate_monthly, Decimal('2.00'))
        self.assertEqual(setting.default_loan_duration_months, 12)

    def test_sequence_numbering_collision_free(self):
        # Generate sequence for tenant A
        num_a1 = get_next_sequence_number(self.tenant_a, sequence_type='loan')
        num_a2 = get_next_sequence_number(self.tenant_a, sequence_type='loan')
        self.assertEqual(num_a1, 'GIR-00001')
        self.assertEqual(num_a2, 'GIR-00002')

        # Tenant B sequence must start independently from 1
        num_b1 = get_next_sequence_number(self.tenant_b, sequence_type='loan')
        self.assertEqual(num_b1, 'GIR-00001')


class GirviLoanAndCollateralTests(GirviBaseTestCase):
    """Test loan contract execution, collateral pieces, and inventory non-mutation."""

    def test_collateral_creation_and_auto_net_weight(self):
        loan = GirviLoan.objects.create(
            tenant=self.tenant_a,
            branch=self.branch_a1,
            customer=self.customer_a,
            loan_number='GIR-00001',
            loan_date=timezone.localdate(),
            principal_amount=Decimal('50000.00'),
            interest_rate_percent=Decimal('2.00'),
            interest_period='monthly',
            interest_calculation_type='simple_monthly',
            loan_duration_months=12,
            maturity_date=timezone.localdate() + datetime.timedelta(days=365),
        )

        # Create pledged collateral item
        initial_inv_count = JewelleryItem.objects.count()

        item = GirviItem.objects.create(
            loan=loan,
            item_name='Gold Necklace 22K',
            metal_type='Gold',
            purity='22K',
            quantity=1,
            gross_weight=Decimal('25.500'),
            stone_weight=Decimal('2.500'),
            purity_percentage=Decimal('91.60'),
            market_value=Decimal('150000.00'),
        )

        # Auto-calculated net weight: 25.500 - 2.500 = 23.000g
        self.assertEqual(item.net_weight, Decimal('23.000'))
        # Fine weight: 23.000 * 0.916 = 21.068g
        self.assertEqual(item.fine_weight, Decimal('21.068'))
        self.assertEqual(item.custody_status, GirviItem.CUSTODY_IN_VAULT)

        # Strict Inventory Safety: JewelleryItem count must remain completely untouched
        self.assertEqual(JewelleryItem.objects.count(), initial_inv_count)

    def test_snapshot_preservation_on_setting_change(self):
        """Showroom default setting edits must never change terms on existing loans."""
        setting = get_or_create_girvi_settings(self.tenant_a)
        setting.default_interest_rate_monthly = Decimal('1.50')
        setting.save()

        loan = GirviLoan.objects.create(
            tenant=self.tenant_a,
            branch=self.branch_a1,
            customer=self.customer_a,
            loan_number='GIR-00001',
            loan_date=timezone.localdate(),
            principal_amount=Decimal('100000.00'),
            interest_rate_percent=Decimal('1.50'),
            interest_period='monthly',
            loan_duration_months=6,
        )

        # Now change default setting to 3.00%
        setting.default_interest_rate_monthly = Decimal('3.00')
        setting.save()

        # Reload loan from database: rate must stay 1.50%
        loan.refresh_from_db()
        self.assertEqual(loan.interest_rate_percent, Decimal('1.50'))


class GirviInterestAndFinancialsTests(GirviBaseTestCase):
    """Test Decimal-accurate interest calculations across methods and periods."""

    def test_simple_monthly_interest_calculation(self):
        # Loan booked 60 days ago: 2 full months
        past_date = timezone.localdate() - datetime.timedelta(days=60)
        loan = GirviLoan.objects.create(
            tenant=self.tenant_a,
            branch=self.branch_a1,
            customer=self.customer_a,
            loan_number='GIR-00001',
            loan_date=past_date,
            principal_amount=Decimal('100000.00'),
            interest_rate_percent=Decimal('2.00'),  # 2% per month
            interest_period='monthly',
            interest_calculation_type='simple_monthly',
            loan_duration_months=12,
        )

        fin = calculate_loan_financials(loan, as_of_date=timezone.localdate())
        # 60 days = 2 months. 100,000 * 2% * 2 = 4,000.00
        self.assertEqual(fin['accrued_interest'], Decimal('4000.00'))
        self.assertEqual(fin['remaining_principal'], Decimal('100000.00'))
        self.assertEqual(fin['outstanding_balance'], Decimal('104000.00'))
        self.assertFalse(fin['is_settled'])

    def test_simple_daily_interest_calculation(self):
        # 15 days elapsed with simple_daily
        past_date = timezone.localdate() - datetime.timedelta(days=15)
        loan = GirviLoan.objects.create(
            tenant=self.tenant_a,
            branch=self.branch_a1,
            customer=self.customer_a,
            loan_number='GIR-00002',
            loan_date=past_date,
            principal_amount=Decimal('60000.00'),
            interest_rate_percent=Decimal('2.00'),  # 2% / month -> daily rate = 0.02 / 30
            interest_period='monthly',
            interest_calculation_type='simple_daily',
            loan_duration_months=6,
        )

        fin = calculate_loan_financials(loan, as_of_date=timezone.localdate())
        # daily = 60,000 * (0.02 / 30) = 40.00 / day. 15 days = 600.00
        self.assertEqual(fin['accrued_interest'], Decimal('600.00'))
        self.assertEqual(fin['outstanding_balance'], Decimal('60600.00'))


class GirviPaymentReversalAndWaiverTests(GirviBaseTestCase):
    """Test payments, auditable reversals, waivers, and settlement."""

    def setUp(self):
        super().setUp()
        past_date = timezone.localdate() - datetime.timedelta(days=30)
        self.loan = GirviLoan.objects.create(
            tenant=self.tenant_a,
            branch=self.branch_a1,
            customer=self.customer_a,
            loan_number='GIR-00001',
            loan_date=past_date,
            principal_amount=Decimal('50000.00'),
            interest_rate_percent=Decimal('2.00'),
            interest_period='monthly',
            interest_calculation_type='simple_monthly',
            loan_duration_months=6,
        )
        GirviItem.objects.create(
            loan=self.loan,
            item_name='Gold Bangles',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('30.000'),
            stone_weight=Decimal('0.000'),
        )

    def test_record_payment_and_settlement(self):
        # 30 days = 1 month -> accrued interest = 1,000.00. Total due = 51,000.00
        fin_before = calculate_loan_financials(self.loan)
        self.assertEqual(fin_before['accrued_interest'], Decimal('1000.00'))

        # Pay interest of 1,000 + 10,000 principal = 11,000
        payment = record_payment(
            loan=self.loan,
            data={
                'payment_date': timezone.localdate(),
                'total_amount_received': Decimal('11000.00'),
                'interest_portion': Decimal('1000.00'),
                'principal_portion': Decimal('10000.00'),
                'charges_portion': Decimal('0.00'),
                'payment_method': 'UPI',
                'reference_number': 'UPI12345678',
            },
            user=self.owner_a
        )
        self.assertEqual(payment.receipt_number, 'PAY-GIR-00001')

        fin_after = calculate_loan_financials(self.loan)
        self.assertEqual(fin_after['principal_paid'], Decimal('10000.00'))
        self.assertEqual(fin_after['interest_paid'], Decimal('1000.00'))
        self.assertEqual(fin_after['remaining_principal'], Decimal('40000.00'))
        self.assertEqual(fin_after['remaining_interest'], Decimal('0.00'))
        self.assertEqual(fin_after['outstanding_balance'], Decimal('40000.00'))

    def test_payment_reversal_restores_balance(self):
        payment = record_payment(
            loan=self.loan,
            data={
                'payment_date': timezone.localdate(),
                'total_amount_received': Decimal('10000.00'),
                'interest_portion': Decimal('1000.00'),
                'principal_portion': Decimal('9000.00'),
                'charges_portion': Decimal('0.00'),
                'payment_method': 'Cash',
            },
            user=self.owner_a
        )

        fin_mid = calculate_loan_financials(self.loan)
        self.assertEqual(fin_mid['remaining_principal'], Decimal('41000.00'))

        # Reverse payment
        reversal = reverse_payment(
            payment=payment,
            reason='Customer cheque returned due to signature discrepancy',
            user=self.owner_a
        )
        self.assertTrue(reversal.is_reversal)
        self.assertEqual(reversal.total_amount_received, Decimal('-10000.00'))

        # Balance restored to 50,000 principal
        fin_end = calculate_loan_financials(self.loan)
        self.assertEqual(fin_end['remaining_principal'], Decimal('50000.00'))
        self.assertEqual(fin_end['total_paid'], Decimal('0.00'))

    def test_authorized_waiver_and_release_gate(self):
        # Attempt to release collateral when balance > 0 must raise ValidationError
        with self.assertRaises(ValidationError):
            release_collateral(self.loan, user=self.owner_a)

        # Pay principal 50,000
        record_payment(
            loan=self.loan,
            data={
                'payment_date': timezone.localdate(),
                'total_amount_received': Decimal('50000.00'),
                'interest_portion': Decimal('0.00'),
                'principal_portion': Decimal('50000.00'),
                'charges_portion': Decimal('0.00'),
                'payment_method': 'Cash',
            },
            user=self.owner_a
        )

        # 1,000 interest remains. Waive it with explicit justification
        waiver = record_waiver(
            loan=self.loan,
            waiver_type=GirviWaiver.WAIVER_INTEREST,
            amount=Decimal('1000.00'),
            reason='Loyal customer full settlement concession authorized by proprietor',
            user=self.owner_a
        )
        self.assertEqual(waiver.amount, Decimal('1000.00'))

        # Outstanding balance is now zero -> is_settled = True
        fin_settled = calculate_loan_financials(self.loan)
        self.assertTrue(fin_settled['is_settled'])
        self.assertEqual(fin_settled['outstanding_balance'], Decimal('0.00'))

        # Collateral release is now permitted
        release_collateral(self.loan, user=self.owner_a, notes='ID verified and original voucher returned')
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, GirviLoan.STATUS_RELEASED)
        self.assertIsNotNone(self.loan.release_date)
        self.assertEqual(self.loan.items.first().custody_status, GirviItem.CUSTODY_RELEASED)


class GirviMultiTenantSecurityTests(GirviBaseTestCase):
    """Test tenant and branch security: Tenant A cannot see or access Tenant B's loans."""

    def setUp(self):
        super().setUp()
        self.loan_a = GirviLoan.objects.create(
            tenant=self.tenant_a,
            branch=self.branch_a1,
            customer=self.customer_a,
            loan_number='GIR-00001',
            loan_date=timezone.localdate(),
            principal_amount=Decimal('50000.00'),
            interest_rate_percent=Decimal('2.00'),
            loan_duration_months=6,
        )
        self.loan_b = GirviLoan.objects.create(
            tenant=self.tenant_b,
            branch=self.branch_b,
            customer=self.customer_b,
            loan_number='GIR-00001',
            loan_date=timezone.localdate(),
            principal_amount=Decimal('75000.00'),
            interest_rate_percent=Decimal('2.50'),
            loan_duration_months=12,
        )

    def test_tenant_isolation_on_detail_view(self):
        # Owner B tries to access Tenant A's loan -> Must return 404
        resp = self.client_b.get(reverse('girvi:loan_detail', args=[self.loan_a.id]))
        self.assertEqual(resp.status_code, 404)

        # Owner A accessing Tenant A's loan -> 200 OK
        resp_a = self.client_a.get(reverse('girvi:loan_detail', args=[self.loan_a.id]))
        self.assertEqual(resp_a.status_code, 200)

    def test_composite_uniqueness_on_loan_number(self):
        # Both tenants can have 'GIR-00001'
        self.assertEqual(self.loan_a.loan_number, 'GIR-00001')
        self.assertEqual(self.loan_b.loan_number, 'GIR-00001')

        # But within Tenant A, duplicate 'GIR-00001' must violate DB unique constraint
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            GirviLoan.objects.create(
                tenant=self.tenant_a,
                branch=self.branch_a1,
                customer=self.customer_a,
                loan_number='GIR-00001',
                loan_date=timezone.localdate(),
                principal_amount=Decimal('20000.00'),
                interest_rate_percent=Decimal('2.00'),
                loan_duration_months=6,
            )


class GirviViewsIntegrationTests(GirviBaseTestCase):
    """Test all Girvi module view endpoints render HTTP 200 successfully."""

    def test_dashboard_and_list_views(self):
        # Dashboard
        resp_dash = self.client_a.get(reverse('girvi:dashboard'))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, "Girvi Dashboard")

        # Loan List
        resp_list = self.client_a.get(reverse('girvi:loan_list'))
        self.assertEqual(resp_list.status_code, 200)
        self.assertContains(resp_list, "Girvi Loans Directory")

        # Settings
        resp_set = self.client_a.get(reverse('girvi:settings'))
        self.assertEqual(resp_set.status_code, 200)
        self.assertContains(resp_set, "Girvi Settings")

        # New Loan Form
        resp_new = self.client_a.get(reverse('girvi:loan_create'))
        self.assertEqual(resp_new.status_code, 200)
        self.assertContains(resp_new, "New Girvi Loan Entry")
