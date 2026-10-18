# v76.7.17.21 · Admin Mobile Schedule

Local candidate only. Based on GitHub v76.7.17.20; no push, deployment, production records or schema changes.

- Compact seven-day mobile selector with the existing date-specific spot and selected day styling. Date/week links stay on the schedule tab.
- Collapsible slot creation on mobile with inputs constrained to the viewport; open on desktop.
- Mobile timetable shows time and all three instructor columns. Full names wrap. Independent shared bookings remain individually accessible, and 2P/3P booking participants remain together.
- Tap a booking for name, booked time range/duration, instructor, spot, status, audit-history link and existing Edit dialog. Completed/No-show remain locked. The booked range is explicitly labeled to avoid implying actual duration.
- Mobile free-slot dialog uses existing POST/CSRF manual-state and booking routes. Instructor assignment/cascade controls are in a collapsible settings section; desktop controls remain available.
- Existing desktop timetable stays intact. Authentic existing branding retained.
- Optional CREATE-MOBILE-DEMO.bat populates only an empty local database with seven demo students' lessons, one 2P group, a Completed and a No-show. Refuses populated databases without deleting anything.

QA: real Admin HTML/render and no-write checks; DOM/JavaScript tests for tap, detail, existing edit action, original-duration guard, history and terminal locking; merge/edit, group completion, instructor pay display, mobile logout and report regression checks in isolated databases. Node DOM QA uses jsdom as an optional development dependency, not a production requirement.

Full browser visual/layout verification at mobile widths remains pending: browser launch was blocked by the runtime's socket permissions. DOM tests are not screenshot/layout verification. Please review locally at 320/390/430px and desktop before publication.
