"""Legal-page and registration evidence integration tests, isolated and offline."""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from unittest.mock import patch

source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)/'app'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','.local_secret_key','uploads','.venv'))
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location('local_launcher',root/'run_local.py')
    launcher=importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
    m=launcher.load_local_app(); m.app.config['TESTING']=True
    client=m.app.test_client(); con=m.db()
    original_users=[tuple(r) for r in con.execute('SELECT id,email,active FROM users ORDER BY id')]
    assert con.execute('SELECT COUNT(*) FROM registration_legal_acceptances').fetchone()[0]==0
    for path,title in [('/terms','Όροι Χρήσης'),('/privacy-policy','Πολιτική Απορρήτου')]:
        response=client.get(path)
        assert response.status_code==200 and title in response.get_data(as_text=True)
        assert 'Προσχέδιο για τοπική δοκιμή' in response.get_data(as_text=True)
        assert client.get(path+'?version=missing').status_code==404
    waiver=client.get('/waiver')
    assert waiver.status_code==200
    html=waiver.get_data(as_text=True)
    for phrase in ('FANI KARAVELA','certify that I am over 18','pro-rated or full refund',"Child's name",'συναίνεση κηδεμόνα'):
        assert phrase in html
    assert 'waiver-original-page-' not in html and 'waiver-scan' not in html
    assert not list((root/'static').rglob('waiver-original-page-*'))
    assert client.get('/waiver?version=missing').status_code==404
    assert client.get('/static/legal/waiver-original-page-1.jpg').status_code==404
    assert client.get('/static/legal/waiver-original-page-2.jpg').status_code==404
    assert client.get('/').status_code==200
    page=client.get('/register').get_data(as_text=True)
    assert 'name="privacy"' in page and 'name="terms_version"' in page
    assert 'target="_blank"' in page and 'υπό τελική δημοσίευση' not in page
    assert 'name="guardian_name"' not in page and 'name="birth_date"' not in page
    def signup(email,**changes):
        with client.session_transaction() as session: session['_csrf_token']='test-legal'
        data=dict(_csrf_token='test-legal',name='QA',surname='Legal',email=email,phone='6900000000',phone_prefix='+30',password='password123',confirm_password='password123',terms='yes',privacy='yes',waiver='yes',terms_version=m.TERMS_VERSION,privacy_version=m.PRIVACY_VERSION,waiver_version=m.WAIVER_VERSION)
        data.update(changes)
        return client.post('/register',data=data)
    for changes in [dict(terms=''),dict(privacy=''),dict(terms_version='outdated'),dict(privacy_version=''),dict(waiver=''),dict(waiver_version='outdated')]:
        assert signup('reject@example.test',**changes).status_code==302
        assert not con.execute("SELECT id FROM users WHERE email='reject@example.test'").fetchone()
        assert con.execute('SELECT COUNT(*) FROM registration_legal_acceptances').fetchone()[0]==0
    with patch.object(m,'issue_confirmation',side_effect=sqlite3.IntegrityError('forced transaction failure')):
        assert signup('rollback@example.test').status_code==302
    assert not con.execute("SELECT id FROM users WHERE email='rollback@example.test'").fetchone()
    assert con.execute('SELECT COUNT(*) FROM registration_legal_acceptances').fetchone()[0]==0
    assert signup('accept@example.test').status_code==200
    uid=con.execute("SELECT id FROM users WHERE email='accept@example.test'").fetchone()[0]
    evidence=con.execute('SELECT a.*,d.body_html,d.sha256 FROM registration_legal_acceptances a JOIN legal_documents d ON d.document_key=a.document_key AND d.version=a.version WHERE a.user_id=?',(uid,)).fetchall()
    assert len(evidence)==3
    assert {r['event'] for r in evidence}=={'accepted','acknowledged'}
    for row in evidence:
        assert row['recorded_at'].endswith('+00:00')
        assert row['document_sha256']==row['sha256']==hashlib.sha256(row['body_html'].encode()).hexdigest()
    assert next(r for r in evidence if r['document_key']=='waiver')['event']=='acknowledged'
    registration=con.execute('SELECT * FROM student_registrations WHERE user_id=?',(uid,)).fetchone()
    assert registration['waiver_version']==m.WAIVER_VERSION and registration['waiver_accepted_at'] is None
    assert registration['lesson_emails']==0 and registration['marketing_emails']==0
    assert signup('lesson-opt-in@example.test',lesson_emails='yes').status_code==200
    prefs=con.execute("SELECT r.lesson_emails,r.marketing_emails FROM student_registrations r JOIN users u ON u.id=r.user_id WHERE u.email='lesson-opt-in@example.test'").fetchone()
    assert tuple(prefs)==(1,0)
    # Existing accounts receive neither fabricated acceptance nor activation changes.
    assert [tuple(r) for r in con.execute('SELECT id,email,active FROM users WHERE id IN ('+','.join('?' for _ in original_users)+') ORDER BY id',[r[0] for r in original_users])]==original_users
    assert not con.execute('SELECT 1 FROM registration_legal_acceptances WHERE user_id=?',(original_users[0][0],)).fetchone()
    with client.session_transaction() as session:
        session['uid']=con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    admin=client.get('/admin/registrations')
    assert admin.status_code==200 and m.TERMS_VERSION in admin.get_data(as_text=True)
    body='<h2>Archived legal test</h2>'
    con.execute("INSERT INTO legal_documents VALUES(?,?,?,?,?,?,?)",('terms','qa-archive','Archive',body,hashlib.sha256(body.encode()).hexdigest(),'16/10/2026','draft')); con.commit()
    assert 'Archived legal test' in client.get('/terms?version=qa-archive').get_data(as_text=True)
    # Changing text without incrementing the version is rejected before setup writes.
    file=root/'templates/legal/terms-2026-10-16-draft1.html'
    file.write_text(file.read_text()+'\nChanged without version\n')
    from legal_pages import setup_legal_pages
    try:
        setup_legal_pages(m.app,m.db)
    except RuntimeError as error:
        assert 'without a new document version' in str(error)
    else:
        raise AssertionError('Legal version mutation was accepted')
    con.close()
    print('PASS: public legal pages, draft notice, exact versions, required acknowledgment, optional consents independent, transactional audit/snapshots, archived documents, unchanged legacy accounts, admin evidence, immutable versions.')
