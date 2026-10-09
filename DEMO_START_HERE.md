# KiteClub v75 Demo Ready

This build automatically creates demo users and test data when the database is empty, both locally and on Railway. No environment variables are needed for an initial demo.

## Local

Install `pip install -r requirements.txt`, then run `python app.py`. Open http://127.0.0.1:5000.

## Railway

Upload the *contents* of this folder to the root of the GitHub repository connected to Railway. Auto-deploy starts when changes are committed to main. Existing SQLite data is **not erased or reseeded** automatically. The app stores a generated session signing key in `DATA_DIR` (if set), otherwise beside app.py. For a persistent Railway setup, mount the existing volume at `/data` and set `DATA_DIR=/data` (or retain the existing valid config).

## Demo credentials (public test accounts only)

- Admin: `admin@kiteclub.gr` / `admin123`
- Student: `student@kiteclub.gr` / `student123`
- Instructor: `angelos@kiteclub.gr` / `teacher123`

**WARNING**: These passwords are predictable. Since booking.kiteclub.gr is a public site, anyone who knows them can access and change your demo data. Never store real personal, payment or customer data in this demo. Before production, disable demo mode (`ENABLE_DEMO_DATA=0`), remove test users, set a strong explicit `SECRET_KEY`, and provision unique long admin credentials.

This build retains v75 CSRF protection, throttling, and security headers.
