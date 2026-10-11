KiteClub v76.3 — Payment Safety

INSTALL OVER EXISTING v76.2.3 (GitHub repository root):
1. Back up the Railway SQLite volume/database BEFORE deployment.
2. Replace ONLY app.py and templates/admin_student_profile.html.
3. Commit and deploy via Railway. Do NOT upload or delete any database files.
4. The application automatically adds a payment_requests table and nullable received_by fields
   to student_payments and lesson_payments on startup; existing payments are preserved.
5. Check version label: KiteClub v76.3 · Payment Safety.

CHANGES
- Central request-id ledger with SQLite uniqueness across both lesson and package payments.
- Legacy idempotency ledgers are consulted for older submission IDs.
- BEGIN IMMEDIATE retains atomic balance and insertion validation.
- Validates nonzero positive EUR amounts with at most two decimals, no overpayment.
- For exact POST replays, responds without registering a new receipt.
- Each new lesson/package installment records the collecting Admin's user ID (received_by).
- Existing records with no collector information display a dash; no invented attribution.
- Normal installments, discounts and package credit rules preserved.

LIMITATIONS / QA REQUIRED
- Flask/browser end-to-end testing was NOT performed in the authoring environment.
- Test request replay, concurrent posts, package and lesson settlement in an ISOLATED
  test database before considering this fully QA approved.
- The direct mark-paid legacy package route and new package purchase creation are
  existing distinct workflows; this patch primarily guards flexible-payment endpoints.
- Do not send payments to a production payment gateway; manual receipts only.
