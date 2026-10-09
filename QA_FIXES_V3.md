# KiteClub v75.2 — QA Fixes v3

Includes previous Reports Hours Fix v1 and Next Lessons Fix v2.

3. Payment Received only for pending payment on active confirmed/pending_payment bookings, server-side atomic conditional update and client-side hidden action. Repeated requests do not create duplicate audit rows.
4. Booking History uses shared Admin sidebar and same styles.
5. Shared APP_VERSION label in Admin, Student, Instructor sidebars: KiteClub v75.2 · QA Fixes v3.

No database schema changes. Test in demo environment before deploying to production.
