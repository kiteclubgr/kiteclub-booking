# KiteClub v75.2 — Admin Reports Hours Fix (1/5)

This release modifies **only** the Admin Reports hours calculations (`/admin/reports`) and adds `tests_reports_hours.py`.

## Counting policy
- Booked: actual occupied instructor time for all non-cancelled bookings, including future and pending bookings.
- Completed: actual occupied instructor time where at least one participant is completed.
- Group/shared participants in the same instructor/time interval count only once towards instructor-hours; student-hours are per participant.
- Different instructors count independently. Cancelled bookings do not count as booked/completed.
- Instructor pay estimate continues to use the hourly rate multiplied by completed physical instructor-hours.
- Weekly completed chart, lesson type breakdown and top student hours use the corrected durations.

## Checks
`python tests_v75.py` and `python tests_reports_hours.py` both pass.
Full Flask/browser deployment testing **has not** been performed in this build environment. Use ChatGPT Work to verify via Railway test deployment after local approval. No Railway deployment was made.

## Example
Two students both booked/completed 10:00–12:00 with one instructor:
Booked instructor-hours=2, completed instructor-hours=2, student-hours=4, instructor pay at 15 EUR/h=30 EUR.
