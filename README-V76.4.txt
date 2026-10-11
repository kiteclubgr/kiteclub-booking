KiteClub v76.4 — Student Debts Management

GitHub patch over v76.3.1. Replace these files at the same relative paths:
app.py
templates/_admin_sidebar_static.html
templates/admin_debts.html (new)

No database migration, deletion, finance/payment workflow change.
The summary is ALL-TIME active debt, not the monthly Finance number.
Test /admin/debts as Admin; filter by lesson/package, amounts, student; click Payment.
The previous v76.3.1 app.py is the base.
