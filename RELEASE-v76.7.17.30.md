# v76.7.17.30 · Password Reset

Adds Forgot password to Login for active Admin, Instructor and Student accounts. Reset URLs expire after 30 minutes, are single-use and are stored only as SHA-256 digests. Opening a URL is read-only; saving requires CSRF-protected POST. New requests rotate older links; changed email/password invalidates outstanding tokens. Reset success revokes prior sessions without automatically signing the user in.

Uses existing email delivery configuration and PUBLIC_BASE_URL. Production email runs in a bounded background pool to keep provider latency off the public response path. Generic responses and database-backed limits reduce enumeration and mail abuse. Delivery is best-effort, without a durable queue or automatic retry after worker interruption.

Creates only password_reset_tokens and password_session_versions if absent. No customer balances, bookings, packages, payments, uploads or secrets are reset or edited. Existing sessions remain valid until their user's password is reset. No Stripe changes are included.

Validation: isolated tests_password_reset.py (including concurrent consumption and background delivery), tests_registration_email.py, tests_google_auth.py, tests_student_home.py passed. Real inbox delivery and mobile reset form require online QA. User authorized main publication for testing.
