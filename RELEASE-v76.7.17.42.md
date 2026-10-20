# v76.7.17.42 · Online Stripe Test

Includes the approved local Student portal updates (.36–.38), Stripe sandbox checkout (.35/.39), payment confirmation (.40), and Dashboard refund synchronization (.41).

## Online test gates
- STRIPE_ONLINE_TEST=1
- PUBLIC_BASE_URL=https://booking.kiteclub.gr (exact fixed HTTPS origin)
- STRIPE_TEST_ENABLED=1 only after private TEST credentials are configured
- STRIPE_SECRET_KEY=sk_test_… or appropriately scoped rk_test_… (never live)
- STRIPE_WEBHOOK_SECRET=whsec_… from the online endpoint, NOT stripe listen
- STRIPE_TEST_STUDENT_EMAILS=qa-stripe@kiteclub.gr (comma-separated explicit approved test accounts)

Only active students whose email is explicitly allowlisted can create checkout or receive payment/refund fulfillment online. Admin can inspect refunds. Ordinary students do not see the TEST purchase controls. No changes to existing customers, bookings, balances or payments are seeded by this release. Startup adds three Stripe tracking tables when online TEST is explicitly configured; existing tables and rows remain intact.

## Stripe sandbox endpoint
URL: https://booking.kiteclub.gr/payments/stripe/webhook
Events:
- checkout.session.completed
- checkout.session.async_payment_succeeded
- checkout.session.expired
- checkout.session.async_payment_failed
- refund.created
- refund.updated
- refund.failed

Keep TEST mode/sandbox selected. Configure the two private credentials directly in Railway Variables, then change STRIPE_TEST_ENABLED from 0 to 1 and redeploy. Never commit keys. No PowerShell listener is needed online. The application will stay disabled until every required setting is present.

Create/choose only the designated test student in Admin; use a non-customer test record with no real lessons. Do not enable demo data or reset the existing database. Test with 4242 4242 4242 4242 and check 1h/60€, refresh protection, declined card, partial refunds 30€ then 30€, financial net totals and replay. For used/reserved hours, review warnings instead of silently modifying lessons.

## Validation
Passed isolated tests_stripe_payments.py (checkout, signatures, group eligibility, rollback, concurrent replay, full/partial refund, failed reversal, used-credit review, finance/reports rendering), tests_stripe_online.py (allowlist, live key rejection, fixed return origin, disabled/missing configuration), tests_student_mobile_shell.py and tests_stripe_confirmation.cjs.

Real online Stripe delivery and Dashboard refund tests remain pending credentials/setup. Disputes, tax receipts and live payments are not implemented. The existing package cancellation button does not issue a Stripe refund.
