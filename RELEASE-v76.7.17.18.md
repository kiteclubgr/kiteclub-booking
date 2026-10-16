# v76.7.17.18 · Merge After Booking Edit

Publication approved 16 October 2026. Existing customer bookings are not automatically modified.
Base: kiteclubgr/kiteclub-booking main 749124e8cd52013a601a03c36dc4407c2f2ff853.

After an Admin saves an edit, compatible adjacent confirmed credit-funded 1h
bookings automatically become one 2h lesson. Supported: private, fixed 2P/3P.
Same students, instructor, day, spot and exact one-hour adjacency required.
No outstanding lesson-debt records, instructor hours, completed attendance,
shared slot occupancy or partially charged participant records are accepted.
Only 1h+1h merges; existing 2h lessons are not extended further.

The merge itself makes no credit/payment/package-balance movements. Existing
charged amounts are combined; existing ledger/usage references follow the survivor.
Subsequent cancellation refunds exactly 2h per participant. Actual private
completion at 1.5h restores exactly 0.5h and logs 1.5h instructor work.
Legitimate edit-related duration/participant changes retain the existing rules.

The larger booking ID survives, preventing reuse of the removed smaller ID by
SQLite's implicit ID allocation. Source booking, participants, slot links and
original credit/usage records are archived in booking_merges as JSON. Original
booking audit rows are retained and included in the combined history. Old Admin
history URLs redirect to the survivor. No fake cancellation is added to reports.
Only an empty archive table is added on startup; no existing bookings auto-merge
on deployment. A subsequent eligible edit/save triggers the merge.

Both Admin edit forms carry the original duration. A stale pre-merge edit cannot
shrink the combined lesson back to one hour on repeat submission. Merge failures
roll back the edit transaction. No emails are sent by the merge.

LOCAL QA
- Real Admin edit route: 1P/2P/3P, forward/reverse chronological ID ordering.
- Balances/ledger amounts/package remaining/debts/receipts unchanged by merge.
- Two slot links, combined participant charges, archived history and redirects.
- Stale edits and source-ID actions do not mutate the survivor.
- Combined cancellation/refund and replay protections.
- Private completion at 1.5h: 0.5h returned once; instructor work 1.5h.
- Unsafe candidates, source ID reuse and archive-write rollback tested.
- Reports hours, package cancellation, syntax/templates/CSRF regression passed.
Browser/mobile visual QA of this edit change remains pending; not certified stable.
