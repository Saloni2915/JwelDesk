"""
super_admin/support_urls.py
---------------------------
Customer support portal URLs and AI Chatbot endpoints.
"""

from django.urls import path
from . import support_views

app_name = 'support_customer'

urlpatterns = [
    # Customer ticket management
    path('tickets/', support_views.customer_ticket_list_view, name='ticket_list'),
    path('tickets/new/', support_views.customer_ticket_create_view, name='ticket_create'),
    path('tickets/<int:ticket_id>/', support_views.customer_ticket_detail_view, name='ticket_detail'),
    path('tickets/<int:ticket_id>/reply/', support_views.customer_ticket_reply_view, name='ticket_reply'),

    # AI Support Chatbot JSON APIs
    path('api/chat/', support_views.api_support_chat, name='api_chat'),
    path('api/create-ticket/', support_views.api_create_ticket, name='api_create_ticket'),
    path('api/topics/', support_views.api_knowledge_topics, name='api_topics'),
]
