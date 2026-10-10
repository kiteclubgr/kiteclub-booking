KiteClub v76.2.3 — Booking Filter Fix

Apply on top of v76.2.2 in GitHub. Replace ONLY:
  app.py
  templates/admin_bookings.html

Changes:
  * Confirmed filter includes ALL bookings with b.status='confirmed',
    regardless of unpaid/partial/paid payment state.
  * Pending payment filter includes only b.status='pending_payment',
    so confirmed-but-unpaid bookings are not incorrectly included.
  * Filter option label and submitted value now read Confirmed.
  * Backward compatibility for old ?status=booked bookmarks.
  * Version updated to KiteClub v76.2.3 · Booking Filter Fix.

No schema migration; no data or financial changes.
QA: /admin/bookings?q=QA-V762-A&status=confirmed must include
#32, #37, #38 (assuming their states remain the same).
Pending filter must exclude #32 while including truly pending #31/#33.
Finance/Reports should remain unchanged. HTTP replay remains NOT TESTED.
