"""Read-only email waiting screen and package context for registration."""
from flask import request, session, render_template, make_response

def setup_registration_waiting(app, db):
    @app.before_request
    def remember_registration_package():
        if request.endpoint == 'register' and request.args.get('package') == 'private-8h':
            session['registration_package'] = 'private-8h'

    @app.get('/register/check-email')
    def registration_check_email():
        preview = request.args.get('preview') == '1'
        language = 'en' if request.args.get('lang') == 'en' else 'el'
        package = None
        if (preview and request.args.get('package') == 'private-8h') or (not preview and session.get('registration_package') == 'private-8h'):
            con = db()
            try:
                row = con.execute("SELECT hours,price FROM packages WHERE active=1 AND package_type='lesson' AND hours=8 AND price>0 ORDER BY id LIMIT 1").fetchone()
                package = dict(row) if row else None
            finally:
                con.close()
        response = make_response(render_template('registration_waiting.html', language=language,
            preview=preview, email=None if preview else session.get('registration_waiting_email'),
            package=package))
        response.headers['Cache-Control'] = 'no-store'
        return response
