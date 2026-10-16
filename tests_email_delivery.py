"""Offline transport tests: no network or real recipients; local preview isolation."""
from email.message import EmailMessage
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
import requests
from email_delivery import deliver_message, missing_email_settings


class EmailDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.context=self.app.app_context(); self.context.push()
        self.env=patch.dict(os.environ,{},clear=True); self.env.start()
        self.message=EmailMessage()
        self.message['From']='KiteClub <booking@example.test>'
        self.message['To']='qa@example.test'
        self.message['Subject']='QA confirmation'
        self.message.set_content('Verification test, no real delivery.')
        self.message.add_alternative('<p>QA confirmation</p>',subtype='html')

    def tearDown(self):
        self.env.stop(); self.context.pop()

    def resend_config(self):
        os.environ.update(EMAIL_PROVIDER='resend',RESEND_API_KEY='fake-key-for-mocked-test',
                          EMAIL_FROM='booking@example.test')

    def test_local_preview_prevents_every_transport_even_if_key_exists(self):
        self.resend_config()
        with tempfile.TemporaryDirectory() as folder:
            self.app.config.update(LOCAL_EMAIL_PREVIEW=True,REGISTRATION_DATA_DIR=folder)
            with patch('email_delivery.requests.post') as http,patch('email_delivery.smtplib.SMTP') as smtp:
                self.assertEqual(deliver_message(self.message),'preview')
                http.assert_not_called();smtp.assert_not_called()
            self.assertEqual(len(list((Path(folder)/'mail-preview').glob('*.eml'))),1)

    def test_missing_settings_sends_nothing(self):
        with patch('email_delivery.requests.post') as http,patch('email_delivery.smtplib.SMTP') as smtp:
            self.assertEqual(deliver_message(self.message),'unavailable')
            http.assert_not_called();smtp.assert_not_called()
        os.environ['EMAIL_PROVIDER']='resend'
        self.assertEqual(missing_email_settings(),['RESEND_API_KEY','EMAIL_FROM'])

    def test_resend_preserves_plain_html_and_reply_to_over_https(self):
        self.resend_config();self.message['Reply-To']='support@example.test'
        with patch('email_delivery.requests.post',return_value=MagicMock(status_code=200)) as http:
            self.assertEqual(deliver_message(self.message,idempotency_key='stable-test'),'sent')
        args,kw=http.call_args
        self.assertEqual(args[0],'https://api.resend.com/emails')
        self.assertEqual(kw['json']['to'],['qa@example.test'])
        self.assertIn('QA confirmation',kw['json']['html'])
        self.assertIn('Verification test',kw['json']['text'])
        self.assertEqual(kw['json']['reply_to'],'support@example.test')
        self.assertEqual(kw['headers']['Idempotency-Key'],'stable-test')
        self.assertEqual(kw['timeout'],15);self.assertFalse(kw['allow_redirects'])

    def test_provider_failures_never_expose_body_key_or_recipient(self):
        self.resend_config()
        with patch('email_delivery.requests.post',return_value=MagicMock(status_code=403,text='secret recipient')),self.assertLogs(self.app.logger,level='WARNING') as logs:
            self.assertEqual(deliver_message(self.message),'unavailable')
        self.assertNotIn('fake-key',str(logs.output));self.assertNotIn('qa@example.test',str(logs.output));self.assertNotIn('secret recipient',str(logs.output))
        with patch('email_delivery.requests.post',side_effect=requests.Timeout('sensitive URL/token')):
            self.assertEqual(deliver_message(self.message),'unavailable')

    def test_smtp_starttls_and_ssl(self):
        os.environ.update(SMTP_HOST='smtp.example.test',SMTP_USER='test-user',SMTP_PASS='fake-pass')
        with patch('email_delivery.smtplib.SMTP') as ctor:
            self.assertEqual(deliver_message(self.message),'sent')
            ctor.assert_called_once_with('smtp.example.test',587,timeout=15)
            smtp=ctor.return_value.__enter__.return_value
            smtp.starttls.assert_called_once();smtp.login.assert_called_once_with('test-user','fake-pass')
            smtp.send_message.assert_called_once()
        os.environ['SMTP_SECURITY']='ssl'
        with patch('email_delivery.smtplib.SMTP_SSL') as ctor:
            self.assertEqual(deliver_message(self.message),'sent')
            self.assertEqual(ctor.call_args.args[:2],('smtp.example.test',465))
            ctor.return_value.__enter__.return_value.starttls.assert_not_called()

    def test_production_cannot_use_local_preview(self):
        self.resend_config()
        self.app.config.update(LOCAL_EMAIL_PREVIEW=True,IS_KITECLUB_PRODUCTION=True)
        with patch('email_delivery.requests.post',return_value=MagicMock(status_code=200)) as http:
            self.assertEqual(deliver_message(self.message),'sent');http.assert_called_once()


if __name__=='__main__':
    unittest.main()
