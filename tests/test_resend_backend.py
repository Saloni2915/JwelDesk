"""
Unit tests for config.resend_backend.ResendEmailBackend.
Tests parsing, payload construction, and error handling with mock urllib responses.
"""
import json
import urllib.error
from unittest.mock import MagicMock, patch
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.test import SimpleTestCase, override_settings
from config.resend_backend import ResendEmailBackend


class ResendEmailBackendTests(SimpleTestCase):
    """Test suite for ResendEmailBackend."""

    def setUp(self):
        self.backend = ResendEmailBackend(api_key='re_test_key_12345', fail_silently=False)

    def test_missing_api_key_raises_when_not_fail_silently(self):
        backend = ResendEmailBackend(api_key='', fail_silently=False)
        msg = EmailMessage('Subject', 'Body', 'test@test.com', ['to@test.com'])
        with self.assertRaises(ValueError):
            backend.send_messages([msg])

    def test_missing_api_key_returns_zero_when_fail_silently(self):
        backend = ResendEmailBackend(api_key='', fail_silently=True)
        msg = EmailMessage('Subject', 'Body', 'test@test.com', ['to@test.com'])
        self.assertEqual(backend.send_messages([msg]), 0)

    @patch('urllib.request.urlopen')
    def test_send_message_constructs_correct_payload(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({'id': 'msg_abc123'}).encode('utf-8')
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        msg = EmailMultiAlternatives(
            subject='Reset Password',
            body='Click here to reset your password: https://jwel-desk.vercel.app',
            from_email='JewelDesk <onboarding@resend.dev>',
            to=['user@example.com'],
            cc=['cc@example.com'],
            bcc=['bcc@example.com'],
            reply_to=['support@example.com'],
        )
        msg.attach_alternative('<p>Click here to reset your password</p>', 'text/html')

        sent_count = self.backend.send_messages([msg])
        self.assertEqual(sent_count, 1)

        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, 'https://api.resend.com/emails')
        self.assertEqual(req.headers['Authorization'], 'Bearer re_test_key_12345')
        self.assertEqual(req.headers['Content-type'], 'application/json')

        payload = json.loads(req.data.decode('utf-8'))
        self.assertEqual(payload['from'], 'JewelDesk <onboarding@resend.dev>')
        self.assertEqual(payload['to'], ['user@example.com'])
        self.assertEqual(payload['cc'], ['cc@example.com'])
        self.assertEqual(payload['bcc'], ['bcc@example.com'])
        self.assertEqual(payload['reply_to'], ['support@example.com'])
        self.assertEqual(payload['subject'], 'Reset Password')
        self.assertIn('Click here', payload['text'])
        self.assertIn('<p>', payload['html'])

    @patch('urllib.request.urlopen')
    def test_unverified_from_domain_safely_falls_back_to_onboarding(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({'id': 'msg_fallback'}).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        msg = EmailMessage('Test', 'Body', 'no-reply@jeweldesk.com', ['user@example.com'])
        self.backend.send_messages([msg])

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode('utf-8'))
        self.assertEqual(payload['from'], 'JewelDesk <onboarding@resend.dev>')

    @patch('urllib.request.urlopen')
    def test_http_error_raises_when_not_fail_silently(self, mock_urlopen):
        err = urllib.error.HTTPError(
            url='https://api.resend.com/emails',
            code=403,
            msg='Forbidden',
            hdrs={},
            fp=MagicMock(read=lambda: b'{"message": "Forbidden test"}')
        )
        mock_urlopen.side_effect = err

        msg = EmailMessage('Test', 'Body', 'JewelDesk <onboarding@resend.dev>', ['to@example.com'])
        with self.assertRaises(RuntimeError) as ctx:
            self.backend.send_messages([msg])
        self.assertIn('403', str(ctx.exception))

    @patch('urllib.request.urlopen')
    def test_http_error_ignored_when_fail_silently(self, mock_urlopen):
        err = urllib.error.HTTPError(
            url='https://api.resend.com/emails',
            code=403,
            msg='Forbidden',
            hdrs={},
            fp=MagicMock(read=lambda: b'{"message": "Forbidden test"}')
        )
        mock_urlopen.side_effect = err

        backend = ResendEmailBackend(api_key='re_test', fail_silently=True)
        msg = EmailMessage('Test', 'Body', 'JewelDesk <onboarding@resend.dev>', ['to@example.com'])
        sent = backend.send_messages([msg])
        self.assertEqual(sent, 0)
