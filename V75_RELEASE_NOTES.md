# KiteClub v75 — Security & Stability

Built on v74; existing data is preserved. Back up your persistent DATA_DIR before deploying.

## Changes
- Server-side CSRF validation on all modifying requests; hidden CSRF token on all POST forms.
- Signing key must be explicitly set to a strong SECRET_KEY on Railway / production. Local development stores a random key in `.local_secret_key` (keep private).
- Secure cookies enforced in production, security response headers and authenticated-page no-store.
- Login failure throttling (8 failures per email over 15 minutes) in SQLite; inactive accounts cannot sign in.
- New installations no longer get publicly known demo credentials by default. Configure ADMIN_EMAIL and ADMIN_PASSWORD (12+ characters). Local demo data requires ENABLE_DEMO_DATA=1 and is blocked in production.
- Removed example passwords from login screen; new student/instructor accounts require an explicit password of at least 12 characters.
- New `backup.py` copies the SQLite DB consistently and includes uploads in a compressed archive, checking integrity first. Schedule externally and store copies off-server.

## Important production checklist
1. Preserve your existing database and uploads; take an external backup first.
2. Set SECRET_KEY to a random secret of 32+ characters and COOKIE_SECURE=1; serve over HTTPS.
3. If deploying against an EMPTY database, set ADMIN_EMAIL and ADMIN_PASSWORD (12+ chars), then remove ADMIN_PASSWORD from the environment after first boot if desired.
4. Reset old weak/demo account passwords in the application. Existing account passwords are NOT changed by v75.
5. Schedule `python backup.py --data-dir /data --output-dir /safe/offserver/backups` via cron/service. Copy archives off-site and periodically test restores. The app itself does NOT schedule backups.
6. If a cached page shows “Invalid or missing security token”, refresh it before submitting.
7. Test all roles and payment, booking, group and progress flows on a staging copy before production rollout.

## Known limits
- Flask was unavailable in the assembly environment, so full integration tests could not be executed there.
- Rate limiting is per email, not a full distributed IP-based WAF.
- Database remains SQLite; concurrency/transaction race testing is a future task.
- Existing passwords are NOT rotated automatically. Further password policies, audit logging, role authorization review and CSP are follow-up work.
