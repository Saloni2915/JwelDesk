"""
tests/test_ai_support_and_tickets.py
------------------------------------
Comprehensive end-to-end test suite for:
1. Grounded AI Support Assistant (English & Hindi/Hinglish, grounded domain knowledge)
2. Floating Chatbot API endpoints and conversation persistence
3. Ticket creation (with file validation and auto-tenant scoping)
4. Customer Ticket Management ("My Support Tickets", filtering, conversation replies)
5. Multi-Tenant Isolation & Privacy (Tenant B blocked from Tenant A; internal notes strictly hidden)
6. Super Admin Support Portal Integration (staff replies, private internal notes, AI summary)
"""

import io
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Tenant
from super_admin.models import (
    PlatformSupportTicket,
    PlatformTicketMessage,
    SupportChatSession,
    SupportChatMessage,
)
from super_admin.ai_assistant import (
    generate_grounded_answer,
    get_ai_support_reply,
    ai_categorize_ticket,
    ai_summarize_ticket,
    find_best_knowledge_match,
)

User = get_user_model()


class AIAssistantEngineTests(TestCase):
    """Verify grounded knowledge retrieval, Hindi/Hinglish matching, and safety constraints."""

    def test_grounded_answer_english_sales_invoice(self):
        query = "How do I create a sales invoice?"
        answer = generate_grounded_answer(query)
        self.assertIn("Sales", answer)
        self.assertTrue("invoice" in answer.lower() or "billing" in answer.lower())
        # Never invent random buttons
        self.assertNotIn("Bitcoin", answer)

    def test_grounded_answer_hindi_inventory(self):
        query = "Naya jewellery stock item kaise add kare?"
        answer = generate_grounded_answer(query)
        # Should return grounded Hindi / Hinglish instructions
        self.assertTrue("stok" in answer.lower() or "jewellery" in answer.lower() or "item" in answer.lower())

    def test_unknown_query_safe_fallback(self):
        query = "How do I launch a spaceship to Mars?"
        answer = generate_grounded_answer(query)
        # Must gracefully admit lack of documented knowledge and suggest human support / raise ticket
        self.assertTrue(
            "Raise a Ticket" in answer or "human support" in answer or "documentation" in answer
        )

    def test_ai_categorize_ticket_heuristics(self):
        category, priority = ai_categorize_ticket(
            "Sales invoice 3% GST calculation mismatch",
            "When generating invoice for gold necklace, tax rate is showing error."
        )
        self.assertEqual(category, "sales")
        self.assertIn(priority, ["high", "urgent"])

    def test_ai_summarize_ticket(self):
        summary = ai_summarize_ticket(
            "Daily gold rate not updating on billing screen",
            "The 24K and 22K rates set in settings are not reflecting automatically on POS checkout.",
            ["Customer: Rates are not showing", "Staff: Investigating database cache"]
        )
        self.assertIn("Core Issue", summary)
        self.assertIn("Daily gold rate", summary)


class CustomerSupportChatAPITests(TestCase):
    """Test AI Support Chatbot JSON endpoints and session persistence."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='jeweller_rajesh',
            email='rajesh@sonijewellers.com',
            password='Password123!',
        )
        self.tenant = Tenant.objects.create(
            name='Soni Jewellers',
            owner=self.user,
            slug='soni-jewellers',
            is_active=True,
        )
        self.client_user = Client()
        self.client_user.login(username='jeweller_rajesh', password='Password123!')

        self.client_anon = Client()

    def test_unauthenticated_chat_allowed_for_visitors(self):
        url = reverse('support_customer:api_chat')
        res = self.client_anon.post(url, {'message': 'Hello, what does JewelDesk do?'}, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(len(data['reply']) > 10)

    def test_authenticated_chat_query_success(self):
        url = reverse('support_customer:api_chat')
        payload = {'message': 'How do I update gold rates?'}
        res = self.client_user.post(url, payload, content_type='application/json')
        self.assertEqual(res.status_code, 200)

        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(len(data['reply']) > 10)
        self.assertTrue(bool(data['session_id']))

        # Verify database session & message creation
        session = SupportChatSession.objects.filter(session_key=data['session_id']).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.user, self.user)
        self.assertEqual(session.tenant, self.tenant)
        self.assertEqual(session.messages.count(), 2)  # User question + Assistant reply

    def test_empty_message_rejected(self):
        url = reverse('support_customer:api_chat')
        res = self.client_user.post(url, {'message': '   '}, content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data['success'])


class TicketCreationAPITests(TestCase):
    """Test direct ticket creation via chatbot API with file upload validation."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='jeweller_mohan',
            email='mohan@royaljewels.com',
            password='Password123!',
        )
        self.tenant = Tenant.objects.create(
            name='Royal Jewels',
            owner=self.user,
            slug='royal-jewels',
            is_active=True,
        )
        self.client_user = Client()
        self.client_user.login(username='jeweller_mohan', password='Password123!')

    def test_create_ticket_from_chat_success(self):
        url = reverse('support_customer:api_create_ticket')
        post_data = {
            'subject': 'Barcode scanner not reading item tags',
            'category': 'inventory',
            'priority': 'medium',
            'description': 'Handheld scanner is beeping but tag code is not populating into invoice item field.',
        }
        res = self.client_user.post(url, post_data)
        self.assertEqual(res.status_code, 200)

        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['ticket_number'].startswith('TICK-') or data['ticket_number'].startswith('TK-'))

        ticket = PlatformSupportTicket.objects.get(id=data['ticket_id'])
        self.assertEqual(ticket.tenant, self.tenant)
        self.assertEqual(ticket.created_by, self.user)
        self.assertEqual(ticket.category, 'inventory')
        self.assertEqual(ticket.priority, 'medium')
        self.assertEqual(ticket.status, PlatformSupportTicket.STATUS_OPEN)

    def test_create_ticket_with_valid_attachment(self):
        url = reverse('support_customer:api_create_ticket')
        valid_img = SimpleUploadedFile(
            name='screenshot.png',
            content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + b'fake_image_bytes',
            content_type='image/png'
        )
        post_data = {
            'subject': 'Display issue on invoice PDF',
            'category': 'sales',
            'priority': 'low',
            'description': 'Logo is slightly shifted on thermal receipt.',
            'attachment': valid_img,
        }
        res = self.client_user.post(url, post_data)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        ticket = PlatformSupportTicket.objects.get(id=data['ticket_id'])
        self.assertTrue(bool(ticket.attachment))

    def test_create_ticket_with_invalid_file_extension(self):
        url = reverse('support_customer:api_create_ticket')
        bad_file = SimpleUploadedFile(
            name='exploit.exe',
            content=b'MZfakeexecutablecode',
            content_type='application/x-msdownload'
        )
        post_data = {
            'subject': 'Malware file test',
            'category': 'technical',
            'priority': 'low',
            'description': 'Attempting to attach disallowed binary.',
            'attachment': bad_file,
        }
        res = self.client_user.post(url, post_data)
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data['success'])
        self.assertIn("Unsupported file type", data['error'])


class MultiTenantIsolationAndPrivacyTests(TestCase):
    """
    STRICT SECURITY TESTS:
    1. Tenant B must NEVER view or access Tenant A's support ticket.
    2. Customer accounts must NEVER see internal staff notes (`is_internal=True`).
    """

    def setUp(self):
        # Tenant A
        self.user_a = User.objects.create_user(
            username='tenant_a_user',
            email='a@jewellers.com',
            password='Password123!',
        )
        self.tenant_a = Tenant.objects.create(
            name='Showroom A',
            owner=self.user_a,
            slug='showroom-a',
            is_active=True,
        )

        # Tenant B
        self.user_b = User.objects.create_user(
            username='tenant_b_user',
            email='b@jewellers.com',
            password='Password123!',
        )
        self.tenant_b = Tenant.objects.create(
            name='Showroom B',
            owner=self.user_b,
            slug='showroom-b',
            is_active=True,
        )

        # Staff Superuser
        self.staff_admin = User.objects.create_superuser(
            username='staff_support_hero',
            email='support@jeweldesk.com',
            password='Password123!',
        )

        # Ticket belonging to Tenant A
        self.ticket_a = PlatformSupportTicket.objects.create(
            tenant=self.tenant_a,
            created_by=self.user_a,
            contact_name='User A',
            contact_email='a@jewellers.com',
            subject='Confidential Tax Question for Showroom A',
            description='Private customer turnover numbers: Rs. 50,00,000.',
            category='sales',
            priority='high',
            status=PlatformSupportTicket.STATUS_OPEN,
        )

        # Add messages to Ticket A: 1 public reply, 1 internal staff note
        self.public_msg = PlatformTicketMessage.objects.create(
            ticket=self.ticket_a,
            sender=self.staff_admin,
            message='Hello User A, we are reviewing your sales records.',
            is_internal=False
        )
        self.internal_note = PlatformTicketMessage.objects.create(
            ticket=self.ticket_a,
            sender=self.staff_admin,
            message='CONFIDENTIAL INTERNAL NOTE: Verify Tenant A subscription status before applying waiver.',
            is_internal=True
        )

        self.client_a = Client()
        self.client_a.login(username='tenant_a_user', password='Password123!')

        self.client_b = Client()
        self.client_b.login(username='tenant_b_user', password='Password123!')

        self.client_staff = Client()
        self.client_staff.login(username='staff_support_hero', password='Password123!')

    def test_tenant_b_cannot_access_tenant_a_ticket(self):
        """Cross-tenant isolation: Tenant B requesting Ticket A must get 404."""
        url = reverse('support_customer:ticket_detail', kwargs={'ticket_id': self.ticket_a.id})
        res = self.client_b.get(url)
        self.assertEqual(res.status_code, 404)

    def test_tenant_b_cannot_reply_to_tenant_a_ticket(self):
        """Cross-tenant isolation: Tenant B attempting to post reply to Ticket A must get 404."""
        url = reverse('support_customer:ticket_reply', kwargs={'ticket_id': self.ticket_a.id})
        res = self.client_b.post(url, {'message': 'Unauthorized intrusion attempt'})
        self.assertEqual(res.status_code, 404)

    def test_customer_cannot_see_internal_notes(self):
        """Privacy guarantee: Internal staff notes must NEVER be sent to customer."""
        url = reverse('support_customer:ticket_detail', kwargs={'ticket_id': self.ticket_a.id})
        res = self.client_a.get(url)
        self.assertEqual(res.status_code, 200)

        # Public message must be present
        self.assertContains(res, 'Hello User A, we are reviewing your sales records.')

        # Internal note MUST NOT BE PRESENT in the HTML response
        self.assertNotContains(res, 'CONFIDENTIAL INTERNAL NOTE')
        self.assertNotContains(res, 'Verify Tenant A subscription status before applying waiver')

    def test_staff_can_view_internal_notes_in_super_admin(self):
        """Super Admin portal properly renders internal notes with staff badges."""
        url = reverse('super_admin:ticket_detail', kwargs={'ticket_id': self.ticket_a.id})
        res = self.client_staff.get(url)
        self.assertEqual(res.status_code, 200)

        # Both public and internal notes must be visible to staff
        self.assertContains(res, 'Hello User A, we are reviewing your sales records.')
        self.assertContains(res, 'CONFIDENTIAL INTERNAL NOTE')
        self.assertContains(res, 'Confidential - Internal Staff Note')

    def test_customer_can_post_reply(self):
        """Customer can reply to their own ticket, updating ticket status."""
        url = reverse('support_customer:ticket_reply', kwargs={'ticket_id': self.ticket_a.id})
        res = self.client_a.post(url, {'message': 'Thank you, here is the additional invoice #1002.'})
        self.assertEqual(res.status_code, 302)

        # Verify message created with is_internal=False
        new_msg = PlatformTicketMessage.objects.filter(
            ticket=self.ticket_a,
            message__icontains='additional invoice #1002'
        ).first()
        self.assertIsNotNone(new_msg)
        self.assertEqual(new_msg.sender, self.user_a)
        self.assertFalse(new_msg.is_internal)

    def test_super_admin_can_post_staff_reply_and_internal_note(self):
        """Staff can post both public replies and private internal notes."""
        url = reverse('super_admin:ticket_staff_reply', kwargs={'ticket_id': self.ticket_a.id})

        # 1. Staff public reply
        res1 = self.client_staff.post(url, {'message': 'Public reply to showroom customer.'})
        self.assertEqual(res1.status_code, 302)
        reply1 = PlatformTicketMessage.objects.filter(message='Public reply to showroom customer.').first()
        self.assertIsNotNone(reply1)
        self.assertFalse(reply1.is_internal)

        # 2. Staff private internal note
        res2 = self.client_staff.post(url, {
            'message': 'Private staff note about DB index.',
            'is_internal': 'on'
        })
        self.assertEqual(res2.status_code, 302)
        reply2 = PlatformTicketMessage.objects.filter(message='Private staff note about DB index.').first()
        self.assertIsNotNone(reply2)
        self.assertTrue(reply2.is_internal)

    def test_super_admin_ai_summary_trigger(self):
        """Super Admin can trigger an AI summary of the ticket."""
        url = reverse('super_admin:ticket_ai_summary', kwargs={'ticket_id': self.ticket_a.id})
        res = self.client_staff.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn('Core Issue', data['ai_summary'])
