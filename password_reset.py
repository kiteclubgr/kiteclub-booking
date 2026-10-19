"""One-use, hashed password reset links; revocation shared across workers."""
import hashlib
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from flask import request, session, render_template, url_for, redirect, flash
from werkzeug.security import generate_password_hash
from email_delivery import deliver_message, email_from


def setup_password_reset(app, db, login_locked, record_attempt):
    c=db()
    try:
        c.executescript('''CREATE TABLE IF NOT EXISTS password_reset_tokens(
            user_id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
            issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            credential_hash TEXT NOT NULL, email TEXT NOT NULL, used_at INTEGER);
            CREATE TABLE IF NOT EXISTS password_session_versions(
            user_id INTEGER PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0);''')
        c.commit()
    finally:c.close()
    def version(uid):
        c=db()
        try:
            r=c.execute('SELECT version FROM password_session_versions WHERE user_id=?',(uid,)).fetchone()
            return r[0] if r else 0
        finally:c.close()
    app.extensions['reset_session_version']=version
    @app.before_request
    def revoke_reset_sessions():
        if session.get('uid') and session.get('password_session_version',0)!=version(session['uid']):
            session.clear()
            flash('Ο κωδικός άλλαξε. Συνδέσου ξανά.')
            return redirect(url_for('login'),303)
    @app.after_request
    def reset_privacy_headers(response):
        if request.endpoint in ('forgot_password','reset_password'):
            response.headers['Cache-Control']='no-store'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['X-Robots-Tag']='noindex, nofollow'
        return response
    pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='password-mail')
    capacity=threading.BoundedSemaphore(4)
    def send_reset_job(email):
        # Account lookup and delivery happen off the public response path to avoid
        # revealing account existence through provider response times.
        try:
            with app.app_context():
                c=db();job=None
                try:
                    c.execute('BEGIN IMMEDIATE')
                    u=c.execute('SELECT id,email,name,password_hash FROM users WHERE lower(email)=? AND active=1',(email,)).fetchone()
                    now=int(time.time())
                    old=c.execute('SELECT issued_at FROM password_reset_tokens WHERE user_id=?',(u['id'],)).fetchone() if u else None
                    if u and (not old or old[0]<=now-60):
                        token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
                        fingerprint=hashlib.sha256(u['password_hash'].encode()).hexdigest()
                        c.execute('''INSERT INTO password_reset_tokens(user_id,token_hash,issued_at,expires_at,credential_hash,email,used_at)
                            VALUES(?,?,?,?,?,?,NULL) ON CONFLICT(user_id) DO UPDATE SET token_hash=excluded.token_hash,
                            issued_at=excluded.issued_at,expires_at=excluded.expires_at,credential_hash=excluded.credential_hash,email=excluded.email,used_at=NULL''',
                            (u['id'],digest,now,now+1800,fingerprint,u['email']))
                        job=(u['email'],u['name'],token,digest)
                    c.commit()
                finally:c.close()
                if job:
                    recipient,name,token,digest=job
                    link=app.config['REGISTRATION_PUBLIC_URL'].rstrip('/')+'/reset-password/'+token
                    msg=EmailMessage();msg['From']=email_from();msg['To']=recipient
                    msg['Subject']='KiteClub — Επαναφορά κωδικού'
                    if os.getenv('EMAIL_REPLY_TO'):msg['Reply-To']=os.environ['EMAIL_REPLY_TO']
                    msg.set_content(app.jinja_env.get_template('emails/password_reset.txt').render(name=name,reset_url=link))
                    msg.add_alternative(app.jinja_env.get_template('emails/password_reset.html').render(name=name,reset_url=link),subtype='html')
                    deliver_message(msg,idempotency_key='password-reset-'+digest)
        except Exception:
            # Never log tokens, mail contents, addresses or provider payloads.
            app.logger.warning('Password reset email could not be prepared or delivered.')
        finally:capacity.release()
    @app.route('/forgot-password',methods=['GET','POST'])
    def forgot_password():
        if request.method=='GET':return render_template('password_reset.html',state='request')
        email=(request.form.get('email') or '').strip().lower()[:254]
        ipkey='password-reset-ip:'+(request.remote_addr or 'unknown')
        emailkey='password-reset-email:'+hashlib.sha256(email.encode()).hexdigest()
        c=db()
        try:
            c.execute('BEGIN IMMEDIATE')
            limited=login_locked(c,ipkey,10) or login_locked(c,emailkey,3)
            if not limited:
                # record_attempt commits; SQLite writer reservation serializes the
                # first check. Recheck email independently before recording it.
                record_attempt(c,ipkey)
                c.execute('BEGIN IMMEDIATE')
                limited=login_locked(c,emailkey,3)
                if not limited:record_attempt(c,emailkey)
            c.commit()
        finally:c.close()
        if not limited and email and '@' in email and capacity.acquire(blocking=False):
            if app.config.get('LOCAL_EMAIL_PREVIEW') or app.config.get('TESTING'):
                send_reset_job(email)
            else:
                try:pool.submit(send_reset_job,email)
                except RuntimeError:capacity.release()
        # Same response/status for absent, inactive, cooldown and throttled users.
        return render_template('password_reset.html',state='sent')
    @app.route('/reset-password/<token>',methods=['GET','POST'])
    def reset_password(token):
        if len(token)>128:return render_template('password_reset.html',state='invalid'),400
        digest=hashlib.sha256(token.encode()).hexdigest()
        c=db()
        try:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('''SELECT r.*,u.password_hash,u.active,u.email AS current_email FROM password_reset_tokens r
                JOIN users u ON u.id=r.user_id WHERE r.token_hash=?''',(digest,)).fetchone()
            if not row or row['used_at'] is not None or row['expires_at']<=int(time.time()) or not row['active'] or row['email']!=row['current_email'] or row['credential_hash']!=hashlib.sha256(row['password_hash'].encode()).hexdigest():
                c.rollback();return render_template('password_reset.html',state='invalid'),400
            if request.method=='GET':
                c.rollback();return render_template('password_reset.html',state='reset')
            password=request.form.get('password','');confirm=request.form.get('confirm_password','')
            if not 10<=len(password)<=128 or password!=confirm:
                c.rollback();return render_template('password_reset.html',state='reset',error='Χρειάζονται 10–128 χαρακτήρες και ίδιος κωδικός στην επιβεβαίωση.'),400
            c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(password),row['user_id']))
            c.execute('UPDATE password_reset_tokens SET used_at=? WHERE user_id=?',(int(time.time()),row['user_id']))
            c.execute('''INSERT INTO password_session_versions(user_id,version) VALUES(?,1)
                ON CONFLICT(user_id) DO UPDATE SET version=version+1''',(row['user_id'],))
            c.commit()
        finally:c.close()
        session.clear()
        flash('Ο κωδικός σου άλλαξε. Συνδέσου με τον νέο κωδικό.','success')
        return redirect(url_for('login'),303)
