# KiteClub v75.1 — Real Admin Dashboard Redesign (Phase 1)

Based on the v75.1 Student Booking Hotfix. The existing operational tabs, booking engine, demo seeding, CSRF, progress calculations, and booking audit history are retained.

## Updated Admin home `/admin`

- Uses the real `static/img/kiteclub-logo.png`.
- Light sidebar with coral/orange selected item, inspired by the approved browser mockup.
- New welcome banner, quick navigation, 4 live KPI tiles.
- Today's bookings table, actual 7-day count chart, live Beginner/Kiter breakdown, recent bookings.
- Zero values / empty states are displayed when there is no data — no mock financial or weather figures.
- Keeps the former detailed Today dashboard in a disclosure labelled “Λεπτομερής διαχείριση σημερινής ημέρας”; the Calendar/Day, Students, and Instructors operational tabs are unchanged.
- Tablet and mobile responsive styles.

## Limitations

This is an **initial real implementation of the Admin Dashboard**, not a pixel-perfect recreation of the conceptual image. The banner is drawn with CSS; no false weather data or invented sea/kitesurf photo is embedded. Full role-wide restyling can follow after feedback.

## Regression checks

`python tests_v75.py`: validates syntax, all Jinja templates, 45 POST forms with CSRF, backup restore.

**Not browser-tested in this environment**: Flask could not be installed due to unavailable package network access. Test locally before publishing to Railway.
