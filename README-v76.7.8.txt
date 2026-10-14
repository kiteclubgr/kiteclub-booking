KiteClub v76.7.8 — GitHub deployment correction

Base: deployed v76.7.7. Upload ALL 4 application files to their exact paths:
- app.py (only APP_VERSION changed)
- templates/admin_equipment.html (displayed version text)
- templates/_admin_sidebar_static.html (the Equipment menu entry)
- static/equipment-v76-7.css (missing inventory styling and icon sizing)

Do not upload/replace kiteclub.db, /data/kiteclub.db, secrets, or .env.
Check https://booking.kiteclub.gr/static/equipment-v76-7.css after Railway deployment (expect CSS, not 404).
Then refresh /admin and /admin/equipment using Ctrl+Shift+R.
