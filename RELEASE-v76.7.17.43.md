# v76.7.17.43 · Refund Status Display

Show full/partial Stripe refunds in Admin student payments, Admin package purchases and Student profile. Full refunds no longer show PAID/settled/active hours, and refunded purchases hide the package cancellation link. Used-credit exceptions retain an explicit review label. Negative payment movements use the debit color. Historical refund labels remain available when TEST is disabled.

Read-only display changes: no balance adjustments, receipt mutations or database migrations. Passed isolated checkout/refund tests plus full-refund rendering in Admin/Student, hidden cancel action and unchanged database dump after rendering, including with TEST disabled. Online allowlist and live-key guards passed. The existing refund handler remains unchanged.
