KiteClub v76.2.2 — Status Label Fix

Apply to existing v76.2.1 GitHub code. Replace only:
  app.py
  templates/admin.html

The application shows Confirmed (rather than Booked) for booking status confirmed, including Admin bookings (shared booking_state_meta), Instructor Lesson Details, and Admin daily schedules (single and shared). Unpaid remains a separate payment label. The slot status booked, booking edit form values, billing, reports and DB schema are unchanged.

Version: KiteClub v76.2.2 · Status Label Fix
Database: no migrations or deletions.
Test after deployment: QA booking #32 Admin Bookings, Admin day view for 2026-10-22, Instructor Lesson Details; verify Confirmed / Unpaid.
The HTTP payment-request replay test remains NOT TESTED.
