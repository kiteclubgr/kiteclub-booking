KiteClub v76.7.7 · Equipment Save Fix

Fixes HTTP 500 on GET /admin/equipment after creating/editing an equipment item.
Root cause: sqlite3.Row in equipment_history was passed to Jinja tojson; now converted to dict.
IMPORTANT: The item may already have been saved before the 500 error. Reopen inventory first and check the code before trying again.
No changes to booking, credits, finance, inventory data, or the database schema.
Full ZIP omits production secrets and any database.
