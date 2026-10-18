# v76.7.17.20 · Instructor Lesson Pay Display

Admin Instructor profile lesson rows now show actual completed duration (with scheduled duration noted when different). Accrued pay uses the same instructor_hours ledger and current rate as the financial summary. No-show rows show zero pay; uncompleted rows explicitly label scheduled pay as a forecast. No schema changes or financial/booking writes.

Validation: tests_instructor_pay_display.py covers real Admin profile render, 1h/1.5h actual duration, legacy null fallback, No-show, future forecast, reconciliation with summary, date filtering and no database writes. Reports and group-completion regressions passed in isolated databases. No real email delivery or production test mutations.

Publication authorized 18 October 2026; verify live Ermina and Xenos profiles after deployment.
