# v76.7.17.15 · Package Purchase Cancellation

Release approved for publication on 16 October 2026. No automatic student correction.

Admin → Students → Student profile → Payments → **Ακύρωση αγοράς**.
A dedicated page requests a reason, calculates a preview, then requires explicit
confirmation. Cancelled purchases remain in history with original value,
UTC timestamp, actor, reason and affected credit/package references.

Unpaid lesson/2P/3P purchases only. Paid/partial purchases, any recorded receipt,
and Crew memberships are blocked. No fictitious receipt is created.
Normal cancellation removes only unused activated credits, requires sufficient
student balance and blocks purchases already consumed by bookings.

For a previous FULL manual removal: Admin explicitly selects the negative manual
ledger movement for this student, confirms its connection to the mistaken purchase,
and selects a replacement purchase if booking consumption exists. The selected
manual movement is reversed in the ledger, the original grant is withdrawn, and
net student credits remain unchanged. Net booking usage is transferred to the
replacement purchase without changing bookings. Future booking refunds therefore
restore the replacement package, not the cancelled purchase.
The same manual movement cannot be used twice. Partial manual corrections require
separate review and are not supported by this workflow.

Original price remains in history; cancelled purchases are excluded from outstanding
debt, cannot accept payments or reactivate credits, and are not counted as paid sales.
Preview signing includes current balances and source/replacement data. Confirmation
rechecks everything under a SQLite write transaction; errors roll back all changes.

No migrations alter existing rows. Startup adds one empty audit table only.
No secrets, uploads, live databases or live customer details are included.

QA: see LOCAL-QA.txt. Mobile/browser QA of cancellation remains pending; no overall stable claim.
