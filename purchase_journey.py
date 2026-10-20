"""Persist a bounded purchase choice through email verification and login."""
from flask import request, session, url_for

def setup_purchase_journey(app, db):
    with db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS registration_purchase_context (
            user_id INTEGER PRIMARY KEY, package_slug TEXT NOT NULL,
            language TEXT NOT NULL)''')
    con.close()

    def language():
        return 'en' if request.args.get('lang', session.get('purchase_language')) == 'en' else 'el'

    @app.before_request
    def remember_choice():
        if request.endpoint in ('register', 'login', 'resend_registration_email'):
            if request.args.get('package') == 'private-8h':
                session['registration_package'] = 'private-8h'
            if request.args.get('lang') in ('el', 'en'):
                session['purchase_language'] = request.args['lang']

    def save_context(con, user_id):
        slug = session.get('registration_package')
        con.execute('''INSERT INTO registration_purchase_context VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET package_slug=excluded.package_slug,
            language=excluded.language''',
            (user_id, slug if slug == 'private-8h' else '', language()))

    def restore_context(con, user_id):
        row = con.execute('SELECT * FROM registration_purchase_context WHERE user_id=?', (user_id,)).fetchone()
        if row:
            session['purchase_language'] = row['language'] if row['language'] in ('el', 'en') else 'el'
            if row['package_slug'] == 'private-8h':
                session['registration_package'] = row['package_slug']

    app.extensions['purchase_save_context'] = save_context
    app.extensions['purchase_restore_context'] = restore_context
    app.extensions['purchase_language'] = language

    def after_login(user_id):
        if session.get('registration_package') == 'private-8h':
            return url_for('student_package_review', lang=language())
        return url_for('home')
    app.extensions['purchase_after_login'] = after_login
