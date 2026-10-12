KiteClub v76.6 — FULL CLEAN DEMO SOURCE FOR GITHUB
================================================

This is the COMPLETE application, assembled from the v76.5.1 complete local
application and the subsequent template/code patches through v76.6 Revised
(shared credits). It is NOT the cancelled separate-credit v76.6 patch.

UPLOAD TO GITHUB
----------------
Extract the ZIP and upload its contents into the repository root, preserving
folders (templates/, static/). Replace matching files. Do not upload the ZIP
itself as an application file. Keep your Railway environment variables.

CLEAN DEMO DATA
---------------
NO kiteclub.db is bundled. When an empty database is used, the app.py initializer
creates demo data, keeps seven original demo student identities, three
instructors, existing catalog/spots, and cleans booking/payment/credit/progress
activity. 2P/3P package catalog: 8h / EUR260 and EUR190 per student.

IMPORTANT: The current production SQLite database on Railway is mounted at
/data/kiteclub.db (DATA_DIR=/data). GitHub deployment DOES NOT delete or reset
this database. The current bookings, debts and test data WILL REMAIN until the
SQLite file on the persistent volume is deliberately replaced/removed under
controlled conditions. Do not remove it while the service is writing.

TESTING STATUS
--------------
This is unchanged v76.6 code; two known issues reported by Work have NOT been
fixed in this clean source package:
(1) Group booking edit from 1h to 2h may create debt despite available credits.
(2) Instructor profile may misallocate Group vs Private completed hours.
DO NOT regard this as production-ready until those bugs are resolved and tested.

No database file, login secrets, Railway volume data, or user uploads included.
