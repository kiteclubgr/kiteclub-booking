"""Versioned local legal drafts and transaction-bound registration acknowledgments."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from flask import abort, render_template, request
from markupsafe import Markup

TERMS_VERSION = '2026-10-16-draft1'
PRIVACY_VERSION = '2026-10-16-draft1'
WAIVER_VERSION = '2026-10-16-original-en-1'
DOCUMENTS = {
    'waiver': (WAIVER_VERSION, 'Συμφωνητικό συμμετοχής — English', 'waiver-2026-10-16-original-en-1.html'),
    'terms': (TERMS_VERSION, 'Όροι Χρήσης', 'terms-2026-10-16-draft1.html'),
    'privacy': (PRIVACY_VERSION, 'Πολιτική Απορρήτου', 'privacy-2026-10-16-draft1.html'),
}


def record_registration_legal(con, user_id):
    """The caller has validated all three checkboxes and exact displayed versions.

    Uses the registration transaction; failed signups leave no acknowledgments.
    A privacy acknowledgment is deliberately not recorded as consent.
    """
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for key, (version, _, _) in DOCUMENTS.items():
        row = con.execute('SELECT sha256 FROM legal_documents WHERE document_key=? AND version=?',
                          (key, version)).fetchone()
        if not row:
            raise RuntimeError('Missing versioned registration document')
        con.execute('''INSERT INTO registration_legal_acceptances
            (user_id,document_key,version,document_sha256,event,recorded_at)
            VALUES(?,?,?,?,?,?)''', (user_id,key,version,row['sha256'],
            'accepted' if key == 'terms' else 'acknowledged',now))


def setup_legal_pages(app, db):
    con = db()
    try:
        con.execute('''CREATE TABLE IF NOT EXISTS legal_documents (
            document_key TEXT NOT NULL, version TEXT NOT NULL, title TEXT NOT NULL,
            body_html TEXT NOT NULL, sha256 TEXT NOT NULL, document_date TEXT NOT NULL,
            status TEXT NOT NULL, PRIMARY KEY(document_key,version))''')
        con.execute('''CREATE TABLE IF NOT EXISTS registration_legal_acceptances (
            user_id INTEGER NOT NULL, document_key TEXT NOT NULL, version TEXT NOT NULL,
            document_sha256 TEXT NOT NULL, event TEXT NOT NULL, recorded_at TEXT NOT NULL,
            PRIMARY KEY(user_id,document_key,version))''')
        for key, (version, title, filename) in DOCUMENTS.items():
            body = (Path(app.root_path)/'templates'/'legal'/filename).read_text(encoding='utf-8')
            digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
            old = con.execute('SELECT sha256 FROM legal_documents WHERE document_key=? AND version=?',
                              (key,version)).fetchone()
            if old and old['sha256'] != digest:
                raise RuntimeError('Legal text changed without a new document version: ' + key)
            con.execute('''INSERT OR IGNORE INTO legal_documents
                (document_key,version,title,body_html,sha256,document_date,status)
                VALUES(?,?,?,?,?,?,?)''', (key,version,title,body,digest,'16/10/2026','transcription' if key == 'waiver' else 'draft'))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    @app.context_processor
    def legal_context():
        return {'terms_version': TERMS_VERSION, 'privacy_version': PRIVACY_VERSION, 'waiver_version': WAIVER_VERSION}

    def show_document(key):
        version = request.args.get('version') or DOCUMENTS[key][0]
        con = db()
        try:
            row = con.execute('SELECT * FROM legal_documents WHERE document_key=? AND version=?',
                              (key,version)).fetchone()
        finally:
            con.close()
        if not row:
            abort(404)
        # Only immutable bundled document HTML is rendered, never request content.
        if hashlib.sha256(row['body_html'].encode('utf-8')).hexdigest() != row['sha256']:
            abort(500)
        return render_template('legal_document.html', document=row, body=Markup(row['body_html']))

    @app.get('/terms')
    def terms_page():
        return show_document('terms')

    @app.get('/privacy-policy')
    def privacy_page():
        return show_document('privacy')

    @app.get('/waiver')
    def waiver_page():
        return show_document('waiver')
