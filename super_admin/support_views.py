"""
super_admin/support_views.py
----------------------------
Customer-facing support portal views and AI chatbot JSON endpoints.
Includes:
1. Customer support ticket list & filtering (strictly multi-tenant scoped)
2. Customer support ticket detail & conversation thread (internal notes excluded)
3. Customer reply submission
4. Floating AI support chatbot API (grounded QA, session persistence, Hindi/Hinglish)
5. Direct ticket creation API from chatbot or web form
"""

import json
import logging
import uuid
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.db.models import Q
from django.urls import reverse

from .models import (
    PlatformSupportTicket,
    PlatformTicketMessage,
    SupportChatSession,
    SupportChatMessage,
    PlatformAuditLog,
)
from .forms_support import (
    CustomerSupportTicketForm,
    CustomerTicketReplyForm,
    validate_support_attachment,
)
from .ai_assistant import (
    generate_grounded_answer,
    ai_categorize_ticket,
    ai_summarize_ticket,
    JEWELDESK_KNOWLEDGE_TOPICS,
)

logger = logging.getLogger(__name__)


def _get_active_tenant(request):
    """Safely obtain the active tenant for the request, falling back if owner."""
    tenant = getattr(request, 'tenant', None)
    if not tenant and request.user.is_authenticated:
        # Check if user owns an active tenant
        tenant = request.user.owned_tenants.filter(is_active=True).first()
    return tenant


# ==============================================================================
# 1. Customer Support Ticket Views (Multi-tenant scoped)
# ==============================================================================

@login_required
def customer_ticket_list_view(request):
    """List support tickets belonging exclusively to the authenticated business tenant."""
    tenant = _get_active_tenant(request)
    
    # Platform super admins without an active tenant see all, or can filter by tenant
    if request.user.is_superuser and not tenant:
        qs = PlatformSupportTicket.objects.all().select_related('tenant', 'assigned_to').order_by('-created_at')
    elif tenant:
        qs = PlatformSupportTicket.objects.filter(tenant=tenant).select_related('assigned_to').order_by('-created_at')
    else:
        # User has no tenant profile
        qs = PlatformSupportTicket.objects.none()

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(ticket_number__icontains=q) |
            Q(subject__icontains=q) |
            Q(description__icontains=q)
        )

    # Status tab filter
    status = request.GET.get('status', 'all').strip()
    if status != 'all' and status:
        qs = qs.filter(status=status)

    # Category filter
    category = request.GET.get('category', 'all').strip()
    if category != 'all' and category:
        qs = qs.filter(category=category)

    # Status counts for badge tabs
    base_qs = PlatformSupportTicket.objects.filter(tenant=tenant) if tenant else PlatformSupportTicket.objects.all()
    all_count = base_qs.count()
    open_count = base_qs.filter(status__in=[PlatformSupportTicket.STATUS_OPEN, PlatformSupportTicket.STATUS_IN_PROGRESS]).count()
    waiting_count = base_qs.filter(status=PlatformSupportTicket.STATUS_WAITING_CUSTOMER).count()
    resolved_count = base_qs.filter(status__in=[PlatformSupportTicket.STATUS_RESOLVED, PlatformSupportTicket.STATUS_CLOSED]).count()

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'status_filter': status,
        'category_filter': category,
        'all_count': all_count,
        'open_count': open_count,
        'waiting_count': waiting_count,
        'resolved_count': resolved_count,
        'status_choices': PlatformSupportTicket.STATUS_CHOICES,
        'category_choices': PlatformSupportTicket.CATEGORY_CHOICES,
        'tenant': tenant,
    }
    return render(request, 'support/customer_ticket_list.html', context)


@login_required
def customer_ticket_detail_view(request, ticket_id):
    """View ticket conversation thread. Strict tenant isolation; internal notes are excluded."""
    tenant = _get_active_tenant(request)

    # Retrieve ticket
    if request.user.is_superuser:
        ticket = get_object_or_404(
            PlatformSupportTicket.objects.select_related('tenant', 'assigned_to'),
            pk=ticket_id
        )
    else:
        if not tenant:
            raise PermissionDenied("You do not have permission to view support tickets.")
        ticket = get_object_or_404(
            PlatformSupportTicket.objects.select_related('tenant', 'assigned_to'),
            pk=ticket_id,
            tenant=tenant
        )

    # Customer can NEVER see internal staff notes
    messages_list = ticket.messages.filter(is_internal=False).select_related('sender').order_by('created_at')

    reply_form = CustomerTicketReplyForm()

    context = {
        'ticket': ticket,
        'messages_list': messages_list,
        'reply_form': reply_form,
        'tenant': tenant,
        'can_reply': ticket.status not in [PlatformSupportTicket.STATUS_CLOSED],
    }
    return render(request, 'support/customer_ticket_detail.html', context)


@login_required
@require_POST
def customer_ticket_reply_view(request, ticket_id):
    """Submit a customer reply to an ongoing ticket."""
    tenant = _get_active_tenant(request)

    if request.user.is_superuser:
        ticket = get_object_or_404(PlatformSupportTicket, pk=ticket_id)
    else:
        if not tenant:
            raise PermissionDenied("You do not have an active business showroom.")
        ticket = get_object_or_404(PlatformSupportTicket, pk=ticket_id, tenant=tenant)

    if ticket.status == PlatformSupportTicket.STATUS_CLOSED:
        messages.warning(request, "This ticket is closed. Please create a new ticket if you require further assistance.")
        return redirect('support_customer:ticket_detail', ticket_id=ticket.id)

    form = CustomerTicketReplyForm(request.POST, request.FILES)
    if form.is_valid():
        msg = form.save(commit=False)
        msg.ticket = ticket
        msg.sender = request.user
        msg.is_internal = False  # Customer replies are ALWAYS public to staff
        msg.save()

        # Update ticket status if it was waiting for customer
        if ticket.status == PlatformSupportTicket.STATUS_WAITING_CUSTOMER:
            ticket.status = PlatformSupportTicket.STATUS_IN_PROGRESS
        ticket.updated_at = timezone.now()
        ticket.save(update_fields=['status', 'updated_at'])

        messages.success(request, "Your reply has been added. The JewelDesk support team has been notified.")
    else:
        error_msg = "Please enter a valid message."
        if 'attachment' in form.errors:
            error_msg = form.errors['attachment'][0]
        messages.error(request, error_msg)

    return redirect('support_customer:ticket_detail', ticket_id=ticket.id)


@login_required
def customer_ticket_create_view(request):
    """Web page form to raise a new support ticket."""
    tenant = _get_active_tenant(request)

    if request.method == 'POST':
        form = CustomerSupportTicketForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.tenant = tenant
            ticket.created_by = request.user
            ticket.contact_name = request.user.get_full_name() or request.user.username
            ticket.contact_email = request.user.email or ''
            
            # AI suggestion enrichment
            cat_sug, pri_sug = ai_categorize_ticket(ticket.subject, ticket.description)
            ticket.ai_suggested_category = cat_sug
            ticket.ai_suggested_priority = pri_sug

            ticket.save()

            messages.success(
                request,
                f"Support Ticket #{ticket.ticket_number} created successfully. Our team will assist you shortly."
            )
            return redirect('support_customer:ticket_detail', ticket_id=ticket.id)
    else:
        form = CustomerSupportTicketForm()

    context = {
        'form': form,
        'tenant': tenant,
    }
    return render(request, 'support/customer_ticket_create.html', context)


# ==============================================================================
# 2. AI Support Chatbot API Endpoints
# ==============================================================================

@require_POST
def api_support_chat(request):
    """
    Handle natural-language customer queries to the JewelDesk AI Assistant across all pages.
    Provides grounded responses, tracks session history, and suggests ticket creation when appropriate.
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    query = data.get('message', '').strip()
    session_id = data.get('session_id', '').strip()

    if not query:
        return JsonResponse({
            'success': False,
            'error': 'Message cannot be empty.'
        }, status=400)

    # Basic length protection
    if len(query) > 2000:
        query = query[:2000]

    user = request.user if request.user.is_authenticated else None
    tenant = _get_active_tenant(request) if user else None

    # Resolve or create chat session for authenticated users
    chat_session = None
    history = []
    if user:
        if session_id:
            chat_session = SupportChatSession.objects.filter(session_key=session_id, user=user).first()
        
        if not chat_session:
            generated_key = session_id or str(uuid.uuid4())
            chat_session = SupportChatSession.objects.create(
                user=user,
                tenant=tenant,
                session_key=generated_key
            )

        # Retrieve last 6 messages from this session for context
        recent_messages = list(
            chat_session.messages.order_by('-created_at')[:6]
        )
        recent_messages.reverse()
        history = [
            {'role': m.role, 'content': m.content}
            for m in recent_messages
        ]

        # Save user message
        SupportChatMessage.objects.create(
            session=chat_session,
            role='user',
            content=query
        )

    # Generate grounded response
    answer = generate_grounded_answer(query, conversation_history=history, user=user, tenant=tenant)

    # Save assistant reply if session exists
    if chat_session:
        SupportChatMessage.objects.create(
            session=chat_session,
            role='assistant',
            content=answer
        )

    # Detect if user asks to raise a ticket or complaint
    suggest_ticket = False
    lower_q = query.lower()
    ticket_triggers = ['ticket', 'complaint', 'agent', 'support person', 'talk to human', 'issue not solved', 'not working', 'bug', 'glitch']
    if any(t in lower_q for t in ticket_triggers) or 'human support' in answer.lower():
        suggest_ticket = True

    # Pre-categorize question for ticket pre-fill
    cat_sug, pri_sug = ai_categorize_ticket(query, answer)

    return JsonResponse({
        'success': True,
        'session_id': str(chat_session.session_key) if chat_session else (session_id or str(uuid.uuid4())),
        'reply': answer,
        'suggest_ticket': suggest_ticket,
        'suggested_category': cat_sug,
        'suggested_priority': pri_sug,
    })


@require_POST
def api_create_ticket(request):
    """
    Direct API endpoint for creating a support ticket from the floating chat widget
    or interactive modal across all pages.
    Supports file attachments (multipart/form-data) and auto-associates with user/tenant if logged in.
    """
    subject = request.POST.get('subject', '').strip()
    category = request.POST.get('category', 'other').strip()
    priority = request.POST.get('priority', 'medium').strip()
    description = request.POST.get('description', '').strip()
    session_id = request.POST.get('session_id', '').strip()
    attachment = request.FILES.get('attachment')

    if not subject:
        return JsonResponse({'success': False, 'error': 'Subject is required.'}, status=400)
    if not description:
        return JsonResponse({'success': False, 'error': 'Description is required.'}, status=400)

    # Attachment validation
    if attachment:
        try:
            validate_support_attachment(attachment)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    user = request.user if request.user.is_authenticated else None
    tenant = _get_active_tenant(request) if user else None

    # Contact details: auto-fill from user if authenticated, or take from form inputs
    contact_name = (user.get_full_name() or user.username) if user else (request.POST.get('contact_name', '').strip() or 'Website Visitor')
    contact_email = (user.email or '') if user else (request.POST.get('contact_email', '').strip() or '')
    contact_phone = (getattr(user, 'phone_number', '') or getattr(tenant, 'phone', '') or '') if user else (request.POST.get('contact_phone', '').strip() or '')

    # Normalize category & priority
    valid_categories = dict(PlatformSupportTicket.CATEGORY_CHOICES).keys()
    if category not in valid_categories:
        category = PlatformSupportTicket.CATEGORY_OTHER

    valid_priorities = dict(PlatformSupportTicket.PRIORITY_CHOICES).keys()
    if priority not in valid_priorities:
        priority = PlatformSupportTicket.PRIORITY_MEDIUM

    # Auto AI categorization & priority suggestion
    cat_sug, pri_sug = ai_categorize_ticket(subject, description)

    ticket = PlatformSupportTicket.objects.create(
        tenant=tenant,
        created_by=user,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        category=category,
        priority=priority,
        status=PlatformSupportTicket.STATUS_OPEN,
        subject=subject,
        description=description,
        attachment=attachment,
        ai_suggested_category=cat_sug,
        ai_suggested_priority=pri_sug,
    )

    # Link ticket context to chat session if provided
    if session_id and user:
        chat_session = SupportChatSession.objects.filter(session_key=session_id, user=user).first()
        if chat_session:
            messages_text = "\n".join([f"{m.role}: {m.content}" for m in chat_session.messages.order_by('created_at')])
            if messages_text:
                ticket.ai_summary = ai_summarize_ticket(subject, description, [messages_text])
                ticket.save(update_fields=['ai_summary'])

    # Audit log
    PlatformAuditLog.objects.create(
        actor=user,
        action='TICKET_CREATE',
        target_tenant=tenant,
        reason=f"{'Customer' if user else 'Website Visitor'} created ticket #{ticket.ticket_number} via AI Assistant: {ticket.subject}",
        ip_address=request.META.get('REMOTE_ADDR', '')[:45],
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )

    detail_url = reverse('support_customer:ticket_detail', kwargs={'ticket_id': ticket.id})

    return JsonResponse({
        'success': True,
        'ticket_number': ticket.ticket_number,
        'ticket_id': ticket.id,
        'detail_url': detail_url,
        'message': f"Ticket #{ticket.ticket_number} created successfully! Our support specialists have been assigned."
    })


@login_required
@require_GET
def api_knowledge_topics(request):
    """Return list of approved help topics for quick question chips in the UI."""
    topics = []
    for item in JEWELDESK_KNOWLEDGE_TOPICS:
        topics.append({
            'key': item.get('id', ''),
            'title': item.get('title', ''),
            'summary': item.get('summary', ''),
            'action_url': item.get('action_url'),
            'action_label': item.get('action_label'),
        })
    return JsonResponse({'success': True, 'topics': topics})
