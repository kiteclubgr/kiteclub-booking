KiteClub v76.3.1 - Booking Counters Fix

Install over v76.3: Replace app.py and templates/admin_bookings.html in GitHub repo root.
No database changes or migration.

- Booking list Pending confirmation metric counts ONLY booking.status == pending_payment, consistent with existing status filter.
- Confirmed/Unpaid and Cancelled are not counted as pending confirmation.
- Renames metric label Pending payment -> Pending confirmation.
- Payment status, payment logic, Finance, Reports, bookings, and credits unchanged.

QA: Filter QA-V762-A: pending confirmation should be 2 (#31 and #33) with status All. Confirmed filter should show 0 pending confirmation. Verify Finance/Reports unaffected.

Offline: Python compilation, Jinja syntax (if available), ZIP integrity. Actual deployed browser QA still required.
