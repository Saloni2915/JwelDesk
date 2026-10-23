"""
Resend Email Backend for Django.

Sends emails via Resend's REST API (https://api.resend.com/emails).
Works reliably in serverless environments (e.g. Vercel, AWS Lambda)
where outbound SMTP ports (25, 465, 587) are blocked or unreliable.
"""
import base64
import json
import logging
import os
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMultiAlternatives

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailBackend(BaseEmailBackend):
    """
    Django EmailBackend implementation that sends emails via Resend's REST API.
    """

    def __init__(self, api_key=None, fail_silently=False, alias=None, **kwargs):
        super().__init__(alias=alias)
        self.fail_silently = fail_silently
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = (
                getattr(settings, 'RESEND_API_KEY', None)
                or os.environ.get('RESEND_API_KEY', '')
            )
        self.default_from = getattr(
            settings,
            'DEFAULT_FROM_EMAIL',
            'JewelDesk <onboarding@resend.dev>'
        )

    def send_messages(self, email_messages):
        """
        Send one or more EmailMessage / EmailMultiAlternatives objects.
        Returns the number of successfully delivered messages.
        """
        if not email_messages:
            return 0

        if not self.api_key:
            err_msg = "Resend API key is not configured (RESEND_API_KEY)."
            logger.error(err_msg)
            if not self.fail_silently:
                raise ValueError(err_msg)
            return 0

        num_sent = 0
        for message in email_messages:
            try:
                if self._send_one(message):
                    num_sent += 1
            except Exception as exc:
                logger.exception("Failed to send email via Resend: %s", exc)
                if not self.fail_silently:
                    raise

        return num_sent

    def _prepare_from(self, from_email):
        """
        Format sender address safely.
        Falls back to onboarding@resend.dev if from_email is unconfigured or
        uses an unverified example/placeholder domain.
        """
        sender = (from_email or self.default_from or '').strip()
        if not sender or '@jeweldesk.com' in sender or '@example.com' in sender:
            # Resend requires onboarding@resend.dev for test accounts unless a custom domain is verified
            if os.environ.get('DEFAULT_FROM_EMAIL'):
                sender = os.environ['DEFAULT_FROM_EMAIL']
            else:
                sender = 'JewelDesk <onboarding@resend.dev>'
        return sender

    def _send_one(self, message):
        """Send a single message via Resend API."""
        from_email = self._prepare_from(message.from_email)
        recipients = [r.strip() for r in message.to if r and r.strip()]
        if not recipients:
            logger.warning("ResendEmailBackend: No recipients for email '%s'", message.subject)
            return False

        # Extract plain text and html bodies
        text_body = ""
        html_body = None

        if getattr(message, 'content_subtype', None) == 'html':
            html_body = message.body
        else:
            text_body = message.body or ""

        if isinstance(message, EmailMultiAlternatives) or hasattr(message, 'alternatives'):
            for content, mimetype in getattr(message, 'alternatives', []):
                if mimetype == 'text/html':
                    html_body = content

        payload = {
            "from": from_email,
            "to": recipients,
            "subject": message.subject or "(No Subject)",
        }
        if html_body:
            payload["html"] = html_body
        if text_body:
            payload["text"] = text_body

        # Handle CC / BCC / Reply-To
        if getattr(message, 'cc', None):
            cc_list = [c.strip() for c in message.cc if c and c.strip()]
            if cc_list:
                payload["cc"] = cc_list
        if getattr(message, 'bcc', None):
            bcc_list = [b.strip() for b in message.bcc if b and b.strip()]
            if bcc_list:
                payload["bcc"] = bcc_list
        if getattr(message, 'reply_to', None):
            reply_to_list = [r.strip() for r in message.reply_to if r and r.strip()]
            if reply_to_list:
                payload["reply_to"] = reply_to_list

        # Attachments handling
        if getattr(message, 'attachments', None):
            attachments_data = []
            for item in message.attachments:
                if isinstance(item, tuple) and len(item) >= 2:
                    filename = item[0]
                    raw_content = item[1]
                    if isinstance(raw_content, str):
                        b64 = base64.b64encode(raw_content.encode('utf-8')).decode('ascii')
                    elif isinstance(raw_content, (bytes, bytearray)):
                        b64 = base64.b64encode(raw_content).decode('ascii')
                    else:
                        continue
                    attachments_data.append({
                        "filename": filename,
                        "content": b64,
                    })
            if attachments_data:
                payload["attachments"] = attachments_data

        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            RESEND_API_URL,
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "JewelDesk/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_body = resp.read().decode('utf-8', errors='replace')
                resp_json = json.loads(resp_body) if resp_body else {}
                msg_id = resp_json.get('id', 'sent')
                logger.info(
                    "Resend email sent successfully (ID: %s) to %s: '%s'",
                    msg_id, recipients, message.subject
                )
                return True
        except urllib.error.HTTPError as exc:
            err_content = exc.read().decode('utf-8', errors='replace')
            logger.error(
                "Resend API HTTPError %s sending to %s: %s",
                exc.code, recipients, err_content
            )
            if not self.fail_silently:
                raise RuntimeError(
                    f"Resend email delivery failed (HTTP {exc.code}): {err_content}"
                ) from exc
            return False
        except Exception as exc:
            logger.error(
                "Resend API network error sending to %s: %s",
                recipients, exc
            )
            if not self.fail_silently:
                raise
            return False
