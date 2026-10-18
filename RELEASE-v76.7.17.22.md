# v76.7.17.22 · Admin Schedule Cleanup

Publication approved after user local testing on 18 October 2026. Includes the mobile redesign documented in RELEASE-v76.7.17.21.md. Removes the entire Day Management card (heading, date input, Open and Rebalance button) from the shared Admin schedule template, on desktop and mobile. Weekly date/spot selector, slot generation, instructor settings, booking details/edit/history remain intact. No backend, booking, credit or payment behavior changes.

Real Admin render regression confirms card and button removal while preserving calendar links and schedule. Full browser visual QA remains pending as documented for .21. No schema or production-data migration. Agent screenshot QA unavailable; user local testing reported success.
