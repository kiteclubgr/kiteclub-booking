"""Public read-only package presentation; checkout remains in existing TEST flow."""
from flask import abort, render_template

def setup_package_pages(app, db, current_user):
    @app.get('/packages/private-8h')
    def public_private_8h():
        con = db()
        try:
            package = con.execute(
                "SELECT id,name,hours,price FROM packages WHERE active=1 AND package_type='lesson' AND hours=8 AND price>0 ORDER BY id LIMIT 1"
            ).fetchone()
            package = dict(package) if package else None
        finally:
            con.close()
        if not package:
            abort(404)
        return render_template('public_package.html', package=package, user=current_user())
