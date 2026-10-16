"""One-use email confirmation. Verified new student accounts activate automatically."""
import hashlib
import os
import secrets
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email_delivery import deliver_message, email_from
from flask import current_app, flash, redirect, render_template, request, url_for


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def issue_confirmation(con, user_id, already_verified=False):
    token = None if already_verified else secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest() if token else None
    now = int(time.time())
    con.execute('''INSERT INTO registration_email_confirmations
        (user_id,token_hash,issued_at,expires_at,verified_at)
        VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
        token_hash=excluded.token_hash,issued_at=excluded.issued_at,
        expires_at=excluded.expires_at,verified_at=excluded.verified_at''',
        (user_id,digest,now,now+86400,stamp() if already_verified else None))
    return token


def activate_verified_registration(con, user_id):
    """Activate only verified signups; retain existing known-minor consent protection.

    Called only during the first successful confirmation or a new verified OAuth
    signup. Never run as a bulk update or on login (disabled accounts stay disabled).
    """
    row = con.execute("""SELECT r.birth_date,r.guardian_approved_at,e.verified_at
        FROM student_registrations r JOIN registration_email_confirmations e
        ON e.user_id=r.user_id WHERE r.user_id=?""", (user_id,)).fetchone()
    if not row or not row['verified_at']:
        return False
    if row['birth_date']:
        birth = datetime.strptime(row['birth_date'], '%Y-%m-%d').date()
        today = datetime.now(timezone.utc).date()
        age = today.year-birth.year-((today.month,today.day)<(birth.month,birth.day))
        if age < 18 and not row['guardian_approved_at']:
            return False
    result = con.execute("UPDATE users SET active=1 WHERE id=? AND role='student' AND active=0",
                         (user_id,))
    return result.rowcount == 1


def send_confirmation(email, name, token):
    base = current_app.config['REGISTRATION_PUBLIC_URL'].rstrip('/')
    link = base + url_for('confirm_registration_email', token=token)
    body = render_template('emails/confirm_registration_email.txt', name=name, confirmation_url=link)
    message = EmailMessage()
    message['From'] = email_from()
    if os.getenv('EMAIL_REPLY_TO'):
        message['Reply-To'] = os.environ['EMAIL_REPLY_TO']
    message['To'] = email
    message['Subject'] = 'KiteClub — Επιβεβαίωση του email σου'
    message.set_content(body)
    message.add_alternative(render_template('emails/confirm_registration_email.html',
                                            name=name, confirmation_url=link), subtype='html')
    return deliver_message(message, idempotency_key='registration-'+hashlib.sha256(token.encode()).hexdigest())


def setup_registration_email(app, db, login_locked, record_attempt):
    with db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS registration_email_confirmations (
            user_id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE,
            issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            verified_at TEXT)''')
    con.close()
    production = app.config.get('IS_KITECLUB_PRODUCTION', False)
    app.config['REGISTRATION_PUBLIC_URL'] = os.getenv('PUBLIC_BASE_URL',
        'https://booking.kiteclub.gr' if production else 'http://127.0.0.1:5000')
    app.config['LOCAL_EMAIL_PREVIEW'] = not production and os.getenv('LOCAL_EMAIL_PREVIEW') == '1'

    @app.route('/register/confirm-email/<token>', methods=['GET', 'POST'])
    def confirm_registration_email(token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        con = db()
        try:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM registration_email_confirmations WHERE token_hash=?',
                              (digest,)).fetchone()
            if not row or row['expires_at'] < int(time.time()) or row['verified_at']:
                con.rollback()
                return render_template('registration_email_status.html', state='invalid'), 400
            if request.method == 'GET':
                con.rollback()
                return render_template('registration_email_status.html', state='confirm')
            con.execute('UPDATE registration_email_confirmations SET verified_at=?,token_hash=NULL '
                        'WHERE user_id=? AND token_hash=?', (stamp(),row['user_id'],digest))
            activated = activate_verified_registration(con, row['user_id'])
            con.commit()
            return render_template('registration_email_status.html', state='verified' if activated else 'guardian_pending')
        finally:
            con.close()

    @app.route('/register/resend-email', methods=['GET', 'POST'])
    def resend_registration_email():
        if request.method == 'GET':
            return render_template('registration_email_status.html', state='resend')
        email = (request.form.get('email') or '').strip().lower()[:254]
        key = 'verify-email-ip:' + (request.remote_addr or 'unknown')
        con = db()
        job = None
        try:
            con.execute('BEGIN IMMEDIATE')
            if login_locked(con, key, 10):
                con.rollback()
                return render_template('registration_email_status.html', state='limited'), 429
            record_attempt(con, key)
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('''SELECT u.id,u.name,u.email,e.issued_at
                FROM registration_email_confirmations e JOIN users u ON u.id=e.user_id
                WHERE lower(u.email)=? AND e.verified_at IS NULL''', (email,)).fetchone()
            if row and row['issued_at'] <= int(time.time()) - 60:
                token = issue_confirmation(con, row['id'])
                job = (row['email'], row['name'], token)
            con.commit()
        finally:
            con.close()
        if job:
            send_confirmation(*job)
        return render_template('registration_email_status.html', state='resent')
