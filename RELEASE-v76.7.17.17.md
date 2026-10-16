# v76.7.17.17 · Package Cancel Button and Mobile Logout

Approved for publication on 16 October 2026.

Admin student payments: red cancellation action follows settlement on the same
row at desktop widths, matching button heights. Narrow screens can wrap.
Cancelled purchases retain their neutral audit-details link.

Includes the prepared v76.7.17.16 shared mobile logout header for Student and
Instructor. Uses existing POST /logout and CSRF; no authentication logic changes.

Verified in a real local Chromium browser: cancellation placement and red style;
mobile role logout at 320/390/430/900px, hidden at desktop 1024px, tap after
scrolling and protected URL redirects after logout. Screenshots use demo data.
HTTP regression tests cover 11 role pages, CSRF, session clearing, safe GET,
package cancellation and unchanged business rows. Physical phone QA pending.

No booking, credit, financial logic, schema, secrets or live data changes.
