"""Read-only email configuration check. Does not import app, open DB or send mail."""
from email_delivery import email_provider, missing_email_settings

if __name__ == '__main__':
    missing = missing_email_settings()
    print('Email provider:', email_provider())
    if missing:
        print('Missing configuration:', ', '.join(missing))
        raise SystemExit(1)
    print('Required settings are present. This does NOT verify DNS, credentials or inbox delivery.')
    print('No message was sent; no secret values were printed.')
