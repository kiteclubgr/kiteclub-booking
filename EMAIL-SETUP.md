# Email delivery — v76.7.17.14

Registration confirmation and existing transactional messages use the same delivery helper.
No real emails were sent during offline QA. Missing configuration or provider failure is
reported safely without exposing credentials/tokens or aborting a saved booking operation.

## Recommended Railway setup: HTTPS / Resend

Railway currently permits SMTP only on Pro and higher. Free, Trial and Hobby must use
an HTTPS email API. Both paths are supported; Resend requires no extra Python dependency.

1. Open an account at https://resend.com and add a sending domain, preferably
   `notify.kiteclub.gr`, in Domains. This is a proposed sender subdomain, not a configured one.
2. In the DNS manager for kiteclub.gr add exactly the records Resend provides and wait
   for verification. Do not invent DNS values, replace the main domain's MX records or
   add a second SPF record to the same host. Receiving email in your existing mailbox
   must remain unchanged. Keep click/open tracking disabled for confirmation links.
3. Create a sending-only API key restricted to that verified domain.
4. In the existing Railway application's Variables, set:

```dotenv
EMAIL_PROVIDER=resend
EMAIL_FROM=KiteClub Booking <booking@notify.kiteclub.gr>
EMAIL_REPLY_TO=sales@kiteclub.gr
RESEND_API_KEY=<paste privately in Railway, never in GitHub or chat>
PUBLIC_BASE_URL=https://booking.kiteclub.gr
LOCAL_EMAIL_PREVIEW=0
```

If you verify a different domain, EMAIL_FROM must use that verified domain instead.
The Reply-To mailbox must be one you actually monitor. This setup does not create a mailbox.

Keep `DATA_DIR=/data`, your existing volume, `SECRET_KEY`, admin credentials and other
production secrets unchanged. For production use `PRODUCTION=1` and `ENABLE_DEMO_DATA=0`.
Never run `run_local.py` on Railway: it is only an isolated local demo launcher.

5. Apply the Variables and redeploy. `python check_email.py` checks only required setting
   presence without printing keys or sending messages; it does not prove connectivity.
6. With an email address YOU control, create one test registration. Check Resend's event
   log and the inbox/spam folder. Check the link points to booking.kiteclub.gr, confirm it,
   then login as the test student. Initial credits must remain zero. No mass email test.

Until a provider is configured, new signups remain unverified and the success page reports
that delivery is unavailable; existing users can still login. After setup, use resend-email
to obtain a new confirmation for a pending account. 'sent' means provider acceptance,
not guaranteed inbox delivery; this version does not implement bounce webhooks or a queue.

## Alternative: existing SMTP mailbox

On Railway Pro/higher, ask your mail host for the actual server and verified sender.
Set EMAIL_PROVIDER=smtp, SMTP_HOST, SMTP_USER, SMTP_PASS, EMAIL_FROM (or legacy SMTP_FROM).
For port 587 use SMTP_SECURITY=starttls; for 465 use SMTP_SECURITY=ssl. No unencrypted mode.
Do not assume the SMTP host from the mailbox domain alone. Account passwords/API keys belong
only in Railway's Variables. Outbound networking and provider policy still need a live test.

## Local testing

START-WINDOWS.bat and run_local.py clear inherited delivery/OAuth secrets and always use
local .eml previews. No actual messages are sent by the local launcher. All QA uses fake
addresses and mocked providers. Tests_email_delivery.py requires only the normal dependencies.

## Sources checked 16 October 2026

- https://docs.railway.com/networking/outbound-networking
- https://resend.com/docs/api-reference/emails/send-email
- https://resend.com/docs/dashboard/domains/introduction

The legal/privacy pages remain visibly local review drafts. Provider, hosting-region,
transfer and retention details must be confirmed before treating the privacy text as final.
