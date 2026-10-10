KiteClub v76.2 — Payment Consistency Fix (GitHub PATCH)

Base: v76.1 — Lesson Payments (the currently deployed GitHub version).

Copy these FOUR changed files into your existing GitHub repository at the same paths:
  app.py
  templates/admin.html
  templates/admin_bookings.html
  templates/admin_student_profile.html

Do not upload the ZIP as a ZIP file; extract then commit the changed files.
No sqlite DB included. Existing Railway volume is untouched; migrations run on app startup.
RECOMMENDED: Back up the Railway SQLite database before deployment.

Changes:
- Finance pending bookings = sum of remaining lesson debt after installments/discounts.
- Editing 1h->2h updates lesson debt to new price while keeping paid amounts.
- Admin can confirm an UNPAID pending lesson without recording revenue: Confirm unpaid.
  Instructor may then mark Completed; payment remains independently outstanding.
- Cancelling an unpaid lesson voids outstanding balance (0 EUR); existing payments stay on record.
- Booking list shows lesson negotiated final price, original price if discounted, and outstanding.
- Removes legacy Payment Received button and disables its POST endpoint.
- Fixes payment history empty notice.
- Sidebar version to v76.2.

QA status: Python syntax, SQL unit smoke, and ZIP integrity tested. Flask browser/runtime
QA NOT DONE here (Flask is not installed in current environment, internet pip blocked).
Important checks with Work before treating as production-ready:
  * 60 EUR lesson + 20 EUR installment -> Finance pending 40 EUR
  * 1h -> 2h lesson -> 110 EUR debt (for one student, no credits)
  * Cancel unpaid -> 0 EUR, original value preserved; no receipts created
  * Cancel partially paid -> paid funds retained, active debt 0 EUR
  * Confirm unpaid -> Completed -> pay afterwards, without status reverting
  * 50 EUR discounted settlement -> 50 EUR in bookings + Finance receipts
  * Idempotency replay and package payments regression
  * Existing Railway data, group bookings, edit with already-paid receipt
