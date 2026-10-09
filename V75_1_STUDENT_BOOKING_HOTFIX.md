# KiteClub v75.1 – Student Booking Hotfix

- Fixed Jinja2 TemplateSyntaxError (unexpected `<`) in `templates/student.html`.
- Repaired the student booking cancellation form so CSRF token appears inside the form, not inside a Jinja expression.
- Preserved the cancellation confirmation for group and private bookings.
- Validated all HTML templates compile, Python app syntax, and POST forms include CSRF tokens.
- No database migration. Includes the preceding v75.1 build.
- Demo-only: do not use live customer data with public demo credentials.

To install locally: extract ZIP and run `python app.py` in the project directory (after installing requirements).
On GitHub: upload the project files at the repository root, excluding `.env`, `.db`, `__pycache__`, `.venv`.
