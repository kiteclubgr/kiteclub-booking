KiteClub v76.6 - Complete GitHub source + clean demo SQLite
===========================================================

This ZIP contains data/kiteclub.db, a freshly generated SQLite database
with 7 demo students, 3 instructors, 3 spots, standard packages and
2P/3P 8-hour packages, and zero bookings, purchases, payments and debts.

CRITICAL RAILWAY STORAGE NOTE
-----------------------------
The live Railway service uses DATA_DIR=/data, where /data is the MOUNTED
PERSISTENT VOLUME web-volume. The data/kiteclub.db file included in this ZIP
will deploy to /app/data/kiteclub.db, NOT to /data/kiteclub.db.
Uploading this ZIP to GitHub DOES NOT REPLACE the existing live database.

To activate the clean database on Railway, the file must be explicitly copied
or uploaded to /data/kiteclub.db with the application stopped/quiesced.
Do not copy an SQLite file while the service is writing to it.
After switching, restart and verify account/booking counts.

The existing v76.6 application logic is unchanged. Two known QA bugs remain:
1. Group booking edited from 1h to 2h may charge money instead of using credits.
2. Admin Instructor Profile can misallocate group/private hours.

The bundled DB has demo account passwords as seeded by app.py. Do not use it
with real customers or publicly exposed demo credentials.
