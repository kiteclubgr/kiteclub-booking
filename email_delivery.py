"""Transactional email via HTTPS or TLS SMTP; no credentials in source or logs."""
import os
from pathlib import Path
import secrets
import smtplib
import ssl

import requests
from flask import current_app


def email_from():
    return os.getenv('EMAIL_FROM') or os.getenv('SMTP_FROM') or 'booking@kiteclub.gr'


def email_provider():
    # Preserve existing configured SMTP deployments unless explicitly changed.
    return os.getenv('EMAIL_PROVIDER', 'smtp').strip().lower()


def missing_email_settings():
    if email_provider() == 'resend':
        return [key for key in ('RESEND_API_KEY','EMAIL_FROM') if not os.getenv(key, '').strip()]
    if email_provider() == 'smtp':
        return [] if os.getenv('SMTP_HOST', '').strip() else ['SMTP_HOST']
    return ['EMAIL_PROVIDER (resend or smtp)']


def deliver_message(message, *, idempotency_key=None):
    if (current_app.config.get('LOCAL_EMAIL_PREVIEW')
            and not current_app.config.get('IS_KITECLUB_PRODUCTION')):
        try:
            folder = Path(current_app.config['REGISTRATION_DATA_DIR'])/'mail-preview'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder/(secrets.token_hex(12)+'.eml')
            with path.open('xb') as output:
                os.chmod(path, 0o600)
                output.write(message.as_bytes())
            return 'preview'
        except OSError:
            current_app.logger.warning('Local email preview could not be saved.')
            return 'unavailable'
    if missing_email_settings():
        current_app.logger.warning('Email not sent: delivery configuration is incomplete.')
        return 'unavailable'
    try:
        if email_provider() == 'resend':
            plain = message.get_body(preferencelist=('plain',))
            html = message.get_body(preferencelist=('html',))
            payload = {'from':str(message['From']), 'to':[str(message['To'])],
                       'subject':str(message['Subject'])}
            if plain:
                payload['text'] = plain.get_content()
            if html:
                payload['html'] = html.get_content()
            if message['Reply-To']:
                payload['reply_to'] = str(message['Reply-To'])
            headers = {'Authorization':'Bearer '+os.environ['RESEND_API_KEY'],
                       'Content-Type':'application/json'}
            if idempotency_key:
                headers['Idempotency-Key'] = idempotency_key
            response = requests.post('https://api.resend.com/emails', headers=headers,
                                     json=payload, timeout=15, allow_redirects=False)
            if not 200 <= response.status_code < 300:
                # Provider responses may contain recipients or tokens: never log them.
                current_app.logger.warning('Email API rejected request (HTTP %d).', response.status_code)
                return 'unavailable'
        else:
            mode = os.getenv('SMTP_SECURITY','starttls').strip().lower()
            if mode not in ('starttls','ssl'):
                raise ValueError('SMTP_SECURITY must be starttls or ssl')
            port = int(os.getenv('SMTP_PORT', '465' if mode == 'ssl' else '587'))
            host = os.environ['SMTP_HOST'].strip()
            context = ssl.create_default_context()
            connection = (smtplib.SMTP_SSL(host,port,timeout=15,context=context)
                          if mode == 'ssl' else smtplib.SMTP(host,port,timeout=15))
            with connection as smtp:
                if mode == 'starttls':
                    smtp.starttls(context=context)
                if os.getenv('SMTP_USER'):
                    smtp.login(os.environ['SMTP_USER'],os.getenv('SMTP_PASS',''))
                smtp.send_message(message)
        return 'sent'  # Accepted by provider, not a claim of inbox delivery.
    except (OSError, smtplib.SMTPException, requests.RequestException, ValueError) as error:
        current_app.logger.warning('Email delivery failed (%s).',type(error).__name__)
        return 'unavailable'
