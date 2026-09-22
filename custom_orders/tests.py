"""
Tests for the custom jewellery orders module.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from inventory.models import Category

from .forms import CustomOrderForm, CustomOrderStatusForm
from .models import CustomOrder


def make_order(**overrides):
    """Build a valid (unsaved) CustomOrder with sensible defaults."""
    customer = overrides.pop('customer', None) or Customer.objects.create(
        name='Test Customer', mobile='9876543210')
    category = overrides.pop('category', None) or Category.objects.create(
        name='Rings')
    defaults = dict(
        customer=customer,
        category=category,
        design_description='Bridal ring with floral engraving',
        metal_type='Gold',
        purity='22K',
        approx_gross_weight=Decimal('10.500'),
        approx_net_weight=Decimal('9.800'),
        making_charge=Decimal('5000.00'),
        estimated_price=Decimal('60000.00'),
        advance_amount=Decimal('10000.00'),
    )
    defaults.update(overrides)
    return CustomOrder(**defaults)


def full_workflow(order):
    """Walk an order through Estimate -> Confirmed -> In Making -> Ready -> Delivered."""
    for status in (CustomOrder.STATUS_ESTIMATE, CustomOrder.STATUS_CONFIRMED,
                   CustomOrder.STATUS_IN_MAKING, CustomOrder.STATUS_READY,
                   CustomOrder.STATUS_DELIVERED):
        order.set_status(status)
    return order

class CustomOrderModelTests(TestCase):
    """Model creation, defaults and field validation."""

    def setUp(self):
        self.customer = Customer.objects.create(
            name='Ravi Kumar', mobile='9990011122')
        self.category = Category.objects.create(name='Necklaces')

    def test_model_creation_and_defaults(self):
        order = make_order(customer=self.customer, category=self.category)
        order.save()
        self.assertEqual(order.status, CustomOrder.STATUS_ENQUIRY)
        self.assertEqual(order.making_charge, Decimal('5000.00'))
        self.assertTrue(order.pk)

    def test_order_number_auto_generated(self):
        order = make_order(customer=self.customer, category=self.category)
        order.save()
        year = timezone.localdate().year
        self.assertEqual(order.order_number, f'CO-{year}-{order.pk:04d}')

    def test_order_numbers_are_unique(self):
        first = make_order(customer=self.customer, category=self.category)
        first.save()
        second = make_order(customer=self.customer, category=self.category)
        second.save()
        self.assertNotEqual(first.order_number, second.order_number)

    def test_customer_is_required(self):
        order = make_order(customer=self.customer, category=self.category)
        order.customer = None
        with self.assertRaises(ValidationError):
            order.full_clean()

    def test_design_description_is_required(self):
        order = make_order(customer=self.customer, category=self.category)
        order.design_description = ''
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn('design_description', ctx.exception.message_dict)

    def test_metal_type_is_required(self):
        order = make_order(customer=self.customer, category=self.category)
        order.metal_type = ''
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn('metal_type', ctx.exception.message_dict)

    def test_negative_gross_weight_rejected(self):
        order = make_order(customer=self.customer, category=self.category)
        order.approx_gross_weight = Decimal('-1')
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn('approx_gross_weight', ctx.exception.message_dict)

    def test_negative_net_weight_rejected(self):
        order = make_order(customer=self.customer, category=self.category)
        order.approx_net_weight = Decimal('-0.5')
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn('approx_net_weight', ctx.exception.message_dict)

    def test_net_weight_cannot_exceed_gross_weight(self):
        order = make_order(customer=self.customer, category=self.category)
        order.approx_net_weight = Decimal('20.000')
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn('approx_net_weight', ctx.exception.message_dict)

    def test_advance_greater_than_estimated_price_rejected(self):
        order = make_order(customer=self.customer, category=self.category)
        order.advance_amount = Decimal('70000.00')
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn('advance_amount', ctx.exception.message_dict)

    def test_remaining_amount_calculation(self):
        order = make_order(customer=self.customer, category=self.category)
        self.assertEqual(order.remaining_amount, Decimal('50000.00'))

    def test_remaining_amount_never_negative(self):
        order = make_order(customer=self.customer, category=self.category)
        order.advance_amount = Decimal('60000.00')
        self.assertEqual(order.remaining_amount, Decimal('0.00'))

    def test_expected_delivery_before_order_date_rejected(self):
        order = make_order(
            customer=self.customer, category=self.category,
            expected_delivery_date=date(2020, 1, 1))
        with self.assertRaises(ValidationError) as ctx:
            order.full_clean()
        self.assertIn('expected_delivery_date', ctx.exception.message_dict)

    def test_customer_relation_and_related_name(self):
        order = make_order(customer=self.customer, category=self.category)
        order.save()
        self.assertIn(order, self.customer.custom_orders.all())

class CustomOrderStatusTests(TestCase):
    """Status workflow transition tests."""

    def setUp(self):
        self.order = make_order()
        self.order.save()

    def test_valid_full_workflow(self):
        full_workflow(self.order)
        self.assertEqual(self.order.status, CustomOrder.STATUS_DELIVERED)

    def test_cancelled_to_in_making_forbidden(self):
        self.order.set_status(CustomOrder.STATUS_CANCELLED)
        self.assertFalse(
            self.order.can_transition_to(CustomOrder.STATUS_IN_MAKING))
        with self.assertRaises(ValidationError):
            self.order.set_status(CustomOrder.STATUS_IN_MAKING)
        self.assertEqual(self.order.status, CustomOrder.STATUS_CANCELLED)

    def test_delivered_to_in_making_forbidden(self):
        full_workflow(self.order)
        with self.assertRaises(ValidationError):
            self.order.set_status(CustomOrder.STATUS_IN_MAKING)
        self.assertEqual(self.order.status, CustomOrder.STATUS_DELIVERED)

    def test_delivery_stamps_actual_delivery_date(self):
        full_workflow(self.order)
        self.assertEqual(
            self.order.actual_delivery_date, timezone.localdate())

    def test_unknown_status_rejected(self):
        with self.assertRaises(ValidationError):
            self.order.set_status('Teleported')

    def test_same_status_is_noop(self):
        self.assertFalse(self.order.set_status(CustomOrder.STATUS_ENQUIRY))
        self.assertEqual(self.order.status, CustomOrder.STATUS_ENQUIRY)

    def test_get_allowed_statuses_for_new_order(self):
        allowed = self.order.get_allowed_statuses()
        self.assertIn(CustomOrder.STATUS_ESTIMATE, allowed)
        self.assertIn(CustomOrder.STATUS_CANCELLED, allowed)
        self.assertNotIn(CustomOrder.STATUS_DELIVERED, allowed)

class CustomOrderFormTests(TestCase):
    """Form-level validation tests."""

    def setUp(self):
        self.customer = Customer.objects.create(
            name='Form Customer', mobile='9887766554')
        self.category = Category.objects.create(name='Bracelets')
        self.valid_data = dict(
            customer=self.customer.pk,
            category=self.category.pk,
            design_description='Temple bangle with peacock motif',
            metal_type='Gold',
            purity='22K',
            approx_gross_weight='15.000',
            approx_net_weight='14.500',
            making_charge='6000.00',
            estimated_price='80000.00',
            advance_amount='20000.00',
            expected_delivery_date=str(
                timezone.localdate() + timedelta(days=20)),
        )

    def test_valid_form(self):
        form = CustomOrderForm(data=self.valid_data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_advance_over_price_rejected_by_form(self):
        self.valid_data['advance_amount'] = '90000.00'
        form = CustomOrderForm(data=self.valid_data)
        self.assertFalse(form.is_valid())
        self.assertIn('advance_amount', form.errors)

    def test_negative_weight_rejected_by_form(self):
        self.valid_data['approx_net_weight'] = '-2'
        form = CustomOrderForm(data=self.valid_data)
        self.assertFalse(form.is_valid())
        self.assertIn('approx_net_weight', form.errors)

    def test_missing_required_fields(self):
        data = {k: v for k, v in self.valid_data.items()
                if k not in ('customer', 'design_description', 'metal_type')}
        form = CustomOrderForm(data=data)
        self.assertFalse(form.is_valid())
        for field in ('customer', 'design_description', 'metal_type'):
            self.assertIn(field, form.errors)

class CustomOrderViewTests(TestCase):
    """View-level tests: list, detail, create, edit, delete, status."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('staff', password='testpass123')
        self.client.login(username='staff', password='testpass123')
        self.customer = Customer.objects.create(
            name='View Customer', mobile='9778899001')
        self.category = Category.objects.create(name='Earrings')
        self.order = make_order(customer=self.customer, category=self.category)
        self.order.save()

    def test_unauthenticated_access_redirects_to_login(self):
        self.client.logout()
        for url in [
            reverse('custom_orders:custom_order_list'),
            reverse('custom_orders:custom_order_add'),
            reverse('custom_orders:custom_order_detail', args=[self.order.pk]),
            reverse('custom_orders:custom_order_edit', args=[self.order.pk]),
            reverse('custom_orders:custom_order_delete', args=[self.order.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn('login', response.url)

    def test_status_update_requires_login(self):
        self.client.logout()
        response = self.client.post(
            reverse('custom_orders:custom_order_status', args=[self.order.pk]),
            {'status': CustomOrder.STATUS_ESTIMATE})
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, CustomOrder.STATUS_ENQUIRY)

    def test_list_view_renders(self):
        response = self.client.get(reverse('custom_orders:custom_order_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'View Customer')

    def test_list_search_by_customer_name(self):
        response = self.client.get(
            reverse('custom_orders:custom_order_list'), {'q': 'View'})
        self.assertContains(response, self.order.order_number)
        response = self.client.get(
            reverse('custom_orders:custom_order_list'), {'q': 'NobodyXYZ'})
        self.assertNotContains(response, self.order.order_number)

    def test_list_search_by_order_number(self):
        response = self.client.get(
            reverse('custom_orders:custom_order_list'),
            {'q': self.order.order_number})
        self.assertContains(response, self.order.order_number)

    def test_list_status_filter(self):
        response = self.client.get(
            reverse('custom_orders:custom_order_list'),
            {'status': CustomOrder.STATUS_ENQUIRY})
        self.assertContains(response, self.order.order_number)
        response = self.client.get(
            reverse('custom_orders:custom_order_list'),
            {'status': CustomOrder.STATUS_DELIVERED})
        self.assertNotContains(response, self.order.order_number)

    def test_list_delivery_filters(self):
        overdue = make_order(
            customer=self.customer, category=self.category)
        overdue.save()
        # Back-date through the queryset (bypasses instance validation) to
        # simulate an order whose delivery date has already passed.
        CustomOrder.objects.filter(pk=overdue.pk).update(
            expected_delivery_date=timezone.localdate() - timedelta(days=3))
        overdue.refresh_from_db()
        response = self.client.get(
            reverse('custom_orders:custom_order_list'),
            {'delivery': 'overdue'})
        self.assertContains(response, overdue.order_number)
        self.assertNotContains(response, self.order.order_number)
        response = self.client.get(
            reverse('custom_orders:custom_order_list'),
            {'delivery': 'due_this_week'})
        # "Due this week" only includes upcoming dates within 7 days,
        # so the already-overdue order above is not listed.
        self.assertNotContains(response, overdue.order_number)
        due_soon = make_order(
            customer=self.customer, category=self.category)
        due_soon.save()
        CustomOrder.objects.filter(pk=due_soon.pk).update(
            expected_delivery_date=timezone.localdate() + timedelta(days=5))
        response = self.client.get(
            reverse('custom_orders:custom_order_list'),
            {'delivery': 'due_this_week'})
        self.assertContains(response, due_soon.order_number)
        # The default fixture is due in 14 days - outside the window.
        self.assertNotContains(response, self.order.order_number)

    def test_detail_view_renders_full_information(self):
        response = self.client.get(
            reverse('custom_orders:custom_order_detail', args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'View Customer')
        self.assertContains(response, 'Bridal ring with floral engraving')
        self.assertContains(response, '22K')
        self.assertContains(response, '60000.00')
        self.assertContains(response, '10000.00')

    def test_detail_view_status_form_offers_only_allowed_transitions(self):
        response = self.client.get(
            reverse('custom_orders:custom_order_detail', args=[self.order.pk]))
        form = response.context['status_form']
        offered = [key for key, _ in form.fields['status'].choices]
        self.assertEqual(set(offered), {'Estimate', 'Cancelled'})
        self.assertNotIn('In Making', offered)
        self.assertNotIn('Delivered', offered)

    def test_detail_view_no_status_form_for_terminal_state(self):
        full_workflow(self.order)
        response = self.client.get(
            reverse('custom_orders:custom_order_detail', args=[self.order.pk]))
        self.assertIsNone(response.context['status_form'])

    def test_create_view_get_renders(self):
        response = self.client.get(reverse('custom_orders:custom_order_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customer')

    def test_create_view_post_creates_order(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_add'),
            data={
                'customer': self.customer.pk,
                'category': self.category.pk,
                'design_description': 'Antique choker',
                'metal_type': 'Gold',
                'purity': '18K',
                'approx_gross_weight': '20.000',
                'approx_net_weight': '19.000',
                'making_charge': '8000.00',
                'estimated_price': '95000.00',
                'advance_amount': '15000.00',
                'expected_delivery_date': str(
                    timezone.localdate() + timedelta(days=15)),
            })
        self.assertEqual(CustomOrder.objects.count(), 2)
        new_order = CustomOrder.objects.order_by('-pk').first()
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_detail',
                              args=[new_order.pk]))
        self.assertEqual(new_order.status, CustomOrder.STATUS_ENQUIRY)
        self.assertEqual(new_order.design_description, 'Antique choker')

    def test_create_view_rejects_invalid_data(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_add'), data={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CustomOrder.objects.count(), 1)

    def test_edit_view_updates_order(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_edit', args=[self.order.pk]),
            data={
                'customer': self.customer.pk,
                'category': self.category.pk,
                'design_description': 'Updated description',
                'metal_type': 'Silver',
                'purity': '925',
                'approx_gross_weight': '5.000',
                'approx_net_weight': '4.500',
                'making_charge': '1000.00',
                'estimated_price': '20000.00',
                'advance_amount': '5000.00',
                'expected_delivery_date': str(
                    timezone.localdate() + timedelta(days=10)),
            })
        self.order.refresh_from_db()
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_detail',
                              args=[self.order.pk]))
        self.assertEqual(self.order.design_description, 'Updated description')
        self.assertEqual(self.order.metal_type, 'Silver')

    def test_edit_blocked_for_delivered_order(self):
        full_workflow(self.order)
        response = self.client.get(
            reverse('custom_orders:custom_order_edit', args=[self.order.pk]))
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_detail',
                              args=[self.order.pk]))

    def test_edit_rejects_invalid_data(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_edit', args=[self.order.pk]),
            data={
                'customer': self.customer.pk,
                'category': self.category.pk,
                'design_description': 'x',
                'metal_type': 'Gold',
                'purity': '22K',
                'approx_gross_weight': '10.000',
                'approx_net_weight': '9.000',
                'making_charge': '5000.00',
                'estimated_price': '60000.00',
                'advance_amount': '99999.00',
                'expected_delivery_date': str(
                    timezone.localdate() + timedelta(days=5)),
            })
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.advance_amount, Decimal('10000.00'))

    def test_delete_removes_enquiry_stage_order(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_delete', args=[self.order.pk]))
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_list'))
        self.assertFalse(
            CustomOrder.objects.filter(pk=self.order.pk).exists())

    def test_delete_confirms_before_removal(self):
        response = self.client.get(
            reverse('custom_orders:custom_order_delete', args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            CustomOrder.objects.filter(pk=self.order.pk).exists())

    def test_cancel_confirmed_order_keeps_record(self):
        self.order.set_status(CustomOrder.STATUS_ESTIMATE)
        self.order.set_status(CustomOrder.STATUS_CONFIRMED)
        response = self.client.post(
            reverse('custom_orders:custom_order_delete', args=[self.order.pk]))
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_detail',
                              args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, CustomOrder.STATUS_CANCELLED)

    def test_delivered_order_cannot_be_deleted(self):
        full_workflow(self.order)
        response = self.client.post(
            reverse('custom_orders:custom_order_delete', args=[self.order.pk]))
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_detail',
                              args=[self.order.pk]))
        self.assertTrue(
            CustomOrder.objects.filter(pk=self.order.pk).exists())

    def test_status_update_via_view(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_status', args=[self.order.pk]),
            {'status': CustomOrder.STATUS_ESTIMATE})
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_detail',
                              args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, CustomOrder.STATUS_ESTIMATE)

    def test_status_update_rejects_invalid_transition(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_status', args=[self.order.pk]),
            {'status': CustomOrder.STATUS_IN_MAKING})
        self.assertRedirects(
            response, reverse('custom_orders:custom_order_detail',
                              args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, CustomOrder.STATUS_ENQUIRY)

class CustomOrderReferenceImageTests(TestCase):
    """Reference image upload and storage tests."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('imgstaff', password='testpass123')
        self.client.login(username='imgstaff', password='testpass123')
        self.customer = Customer.objects.create(
            name='Image Customer', mobile='9665544332')
        self.category = Category.objects.create(name='Pendants')
        self.valid_data = dict(
            customer=self.customer.pk,
            category=self.category.pk,
            design_description='Peacock pendant with matching jhumkas',
            metal_type='Gold',
            purity='22K',
            approx_gross_weight='8.000',
            approx_net_weight='7.500',
            making_charge='3000.00',
            estimated_price='45000.00',
            advance_amount='5000.00',
            expected_delivery_date=str(
                timezone.localdate() + timedelta(days=12)),
        )

    def test_reference_image_upload_via_model(self):
        upload = SimpleUploadedFile(
            'reference.png', b'\x89PNG\r\n\x1a\nfake-image-bytes',
            content_type='image/png')
        order = make_order(
            customer=self.customer, category=self.category,
            reference_image=upload)
        order.save()
        self.assertTrue(order.reference_image)
        self.assertIn('reference.png', order.reference_image.name)
        self.assertTrue(order.reference_image.storage.exists(
            order.reference_image.name))
        order.reference_image.delete(save=False)

    def test_reference_image_upload_via_view(self):
        upload = SimpleUploadedFile(
            'design.jpg', b'fake-jpeg-bytes', content_type='image/jpeg')
        response = self.client.post(
            reverse('custom_orders:custom_order_add'),
            data={**self.valid_data, 'reference_image': upload})
        self.assertEqual(response.status_code, 302)
        order = CustomOrder.objects.order_by('-pk').first()
        self.assertTrue(order.reference_image)
        self.assertIn('design', order.reference_image.name)
        order.reference_image.delete(save=False)

    def test_reference_image_invalid_extension_rejected(self):
        upload = SimpleUploadedFile(
            'malware.exe', b'not-an-image',
            content_type='application/x-msdownload')
        response = self.client.post(
            reverse('custom_orders:custom_order_add'),
            data={**self.valid_data, 'reference_image': upload})
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('reference_image', form.errors)

    def test_reference_image_optional(self):
        response = self.client.post(
            reverse('custom_orders:custom_order_add'), data=self.valid_data)
        self.assertEqual(response.status_code, 302)
        order = CustomOrder.objects.order_by('-pk').first()
        self.assertFalse(order.reference_image)

class CustomerIntegrationTests(TestCase):
    """Custom orders surfaced on the existing customer detail page."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('custstaff', password='testpass123')
        self.client.login(username='custstaff', password='testpass123')
        self.customer = Customer.objects.create(
            name='Integrated Customer', mobile='9554433221')
        self.category = Category.objects.create(name='Bangles')
        self.order = make_order(customer=self.customer, category=self.category)
        self.order.save()

    def test_customer_detail_shows_custom_orders_section(self):
        response = self.client.get(
            reverse('customer_detail', args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'Custom Orders')
        self.assertContains(response, 'New Custom Order')

    def test_add_view_prefills_customer_from_query_param(self):
        response = self.client.get(
            reverse('custom_orders:custom_order_add'),
            {'customer': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(form.initial.get('customer'), self.customer.pk)

    def test_customer_delete_protected_by_custom_orders(self):
        response = self.client.post(
            reverse('customer_delete', args=[self.customer.pk]))
        self.assertTrue(
            Customer.objects.filter(pk=self.customer.pk).exists())










