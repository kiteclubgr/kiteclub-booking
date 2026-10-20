"""Google OpenID Connect; tokens stay server-side and are never stored."""
import os
import time
from flask import abort, flash, redirect, session, url_for, request
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from requests.exceptions import RequestException
from authlib.jose.errors import JoseError


def pending_google():
    identity = session.get('google_identity')
    if not isinstance(identity, dict) or identity.get('expires', 0) <= time.time():
        session.pop('google_identity', None)
        return None
    return identity


def setup_google(app, db, csrf_token):
    client_id = os.getenv('GOOGLE_CLIENT_ID', '').strip()
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '').strip()
    callback = os.getenv('GOOGLE_REDIRECT_URI', 'https://booking.kiteclub.gr/auth/google/callback').strip()
    enabled = bool(client_id and client_secret)
    oauth = OAuth(app)
    google = oauth.register(
        name='google', client_id=client_id, client_secret=client_secret,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256', 'timeout': 15},
    )

    @app.context_processor
    def google_context():
        return {'google_enabled': enabled, 'google_pending': pending_google()}

    @app.post('/auth/google')
    def google_login():
        if not enabled:
            flash('Η σύνδεση Google δεν έχει ενεργοποιηθεί ακόμη.')
            return redirect(url_for('login',lang=session.get('purchase_language','el')))
        session.pop('google_identity', None)
        try:
            return google.authorize_redirect(callback, prompt='select_account')
        except (OAuthError, RequestException):
            flash('Η Google δεν είναι διαθέσιμη αυτή τη στιγμή. Δοκιμάστε ξανά.')
            return redirect(url_for('login',lang=session.get('purchase_language','el')))

    @app.get('/auth/google/callback')
    def google_callback():
        if not enabled:
            abort(404)
        if not session.get('_state_google_' + str(request.args.get('state', ''))):
            flash('Η σύνδεση Google έληξε. Δοκιμάστε ξανά.')
            return redirect(url_for('login',lang=session.get('purchase_language','el')))
        try:
            token = google.authorize_access_token()
            # Authlib verifies signature, issuer, audience, expiry and nonce.
            info = token.get('userinfo')
            if not info or info.get('email_verified') is not True or not info.get('sub'):
                raise ValueError('Unverified identity')
            email = str(info.get('email', '')).strip().lower()
            if not email or len(email) > 254:
                raise ValueError('Invalid email')
        except (OAuthError, RequestException, JoseError, ValueError):
            flash('Δεν ολοκληρώθηκε η επιβεβαίωση Google. Δοκιμάστε ξανά.')
            return redirect(url_for('login',lang=session.get('purchase_language','el')))
        con = db()
        try:
            user = con.execute('SELECT u.* FROM oauth_identities o JOIN users u ON u.id=o.user_id WHERE o.provider=? AND o.subject=?', ('google', info['sub'])).fetchone()
            if user:
                if not user['active']:
                    session.clear()
                    flash('Ο λογαριασμός σας αναμένει έγκριση από τη σχολή ή είναι ανενεργός.')
                    return redirect(url_for('login',lang=session.get('purchase_language','el')))
                purchase_context={k:session[k] for k in ("registration_package","purchase_language") if k in session}
                session.clear()
                session.update(purchase_context)
                session['uid'], session['role'] = user['id'], user['role']
                session['password_session_version'] = app.extensions['reset_session_version'](user['id'])
                session.permanent = True
                csrf_token()
                return redirect(app.extensions['purchase_after_login'](user['id']) if user['role']=='student' else url_for('home'))
            existing = con.execute('SELECT id FROM users WHERE lower(email)=?', (email,)).fetchone()
        finally:
            con.close()
        purchase_context={k:session[k] for k in ('registration_package','purchase_language') if k in session}
        session.clear()
        session.update(purchase_context)
        session['google_identity'] = {'sub': str(info['sub']), 'email': email,
            'name': str(info.get('given_name', ''))[:100],
            'surname': str(info.get('family_name', ''))[:100], 'expires': time.time() + 900}
        if existing:
            flash('Για να συνδέσετε το Google με τον υπάρχοντα λογαριασμό, συνδεθείτε μία φορά με το email και τον κωδικό σας.')
            return redirect(url_for('login',lang=session.get('purchase_language','el')))
        flash('Το email επιβεβαιώθηκε από τη Google. Συμπληρώστε τα υπόλοιπα στοιχεία για εγγραφή.')
        return redirect(url_for('register',lang=session.get('purchase_language','el')))

    return google

