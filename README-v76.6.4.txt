KiteClub v76.6.4 · Instructor Mobile Admin Style — FULL SOURCE

Complete app source for local test / GitHub deployment.
Based on user supplied v76.6.3 full source + instructor mobile layout patch.

Updates:
- Instructor mobile Schedule & Students use compact Admin-inspired layout.
- Shorter banner, smaller profile/stats cards, less scrolling.
- Instructor mobile hamburger menu includes visible Logout.
- Version changed in app.py and therefore the role sidebars.
- All server-side booking, credits, payments, reports logic unchanged.

Install locally:
  pip install -r requirements.txt
  python app.py
For production configure DATA_DIR=/data and existing Railway volume; never replace /data/kiteclub.db.

Security: Real databases, .env values, and .local_secret_key are EXCLUDED.
The app may initialize demo users on an empty local DB unless ENABLE_DEMO_DATA=0.
Avoid using demo mode in production.

Validation: Python compile and Jinja template parse (no live mobile browser test).
