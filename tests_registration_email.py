"""Run against an isolated copy: never reads an existing database or sends mail."""
import importlib.util
import sys
import tempfile
import shutil
from pathlib import Path
from email import policy
from email.parser import BytesParser
import re

source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)/'app'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','.local_secret_key','uploads','.venv'))
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location('local_launcher',root/'run_local.py')
    launcher=importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
    m=launcher.load_local_app(); m.app.config['TESTING']=True
    c=m.app.test_client()
    def csrf():
        with c.session_transaction() as session:
            session['_csrf_token']='qa-token'
        return {'_csrf_token':'qa-token'}
    def post(path,**data):
        return c.post(path,data={**csrf(),**data})
    page=c.get('/register').get_data(as_text=True)
    assert 'name="phone_prefix"' in page and re.search(r'<option\b[^>]*value="\+30"[^>]*\bselected\b',page)
    assert 'name="birth_date"' not in page and 'name="guardian_name"' not in page
    response=post('/register',name='Test',surname='Student',email='qa@example.test',phone='6900000000',password='password123',confirm_password='password123',terms='yes',privacy='yes',terms_version=m.TERMS_VERSION,privacy_version=m.PRIVACY_VERSION,waiver_version=m.WAIVER_VERSION,waiver='yes')
    assert response.status_code==200
    con=m.db(); uid=con.execute("SELECT id FROM users WHERE email='qa@example.test'").fetchone()[0]
    assert con.execute('SELECT active FROM users WHERE id=?',(uid,)).fetchone()[0]==0
    assert con.execute('SELECT phone FROM users WHERE id=?',(uid,)).fetchone()[0]=='+306900000000'
    assert con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]==0
    mail=list((root/'_local_data/mail-preview').glob('*.eml')); assert len(mail)==1
    body=BytesParser(policy=policy.default).parsebytes(mail[0].read_bytes()).get_body(preferencelist=('plain',)).get_content()
    path=re.search(r'http://127.0.0.1:5000(/register/confirm-email/[\w-]+)',body)[1]
    digest=con.execute('SELECT token_hash FROM registration_email_confirmations WHERE user_id=?',(uid,)).fetchone()[0]
    assert digest!=path.rsplit('/',1)[1]
    assert c.get(path).status_code==200
    assert not con.execute('SELECT verified_at FROM registration_email_confirmations WHERE user_id=?',(uid,)).fetchone()[0]
    assert c.post(path).status_code==400
    with c.session_transaction() as session: session['uid']=con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    post(f'/admin/registrations/{uid}/approve',manual_review='yes')
    assert con.execute('SELECT active FROM users WHERE id=?',(uid,)).fetchone()[0]==0
    activated_response=post(path)
    assert activated_response.status_code==303
    assert activated_response.headers['Location']=='/'
    with c.session_transaction() as session:
        assert any('Ο λογαριασμός σου ενεργοποιήθηκε' in message for category,message in session.get('_flashes', []))
    assert c.get(path).status_code==400
    assert con.execute('SELECT active FROM users WHERE id=?',(uid,)).fetchone()[0]==1
    assert con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]==0
    visitor=m.app.test_client()
    with visitor.session_transaction() as session: session['_csrf_token']='visitor-token'
    assert visitor.post('/',data={'_csrf_token':'visitor-token','email':'qa@example.test','password':'password123'}).status_code==302
    with visitor.session_transaction() as session: assert session['uid']==uid
    # Replaying confirmation cannot re-enable an account later disabled by Admin.
    con.execute('UPDATE users SET active=0 WHERE id=?',(uid,)); con.commit()
    assert post(path).status_code==400
    assert con.execute('SELECT active FROM users WHERE id=?',(uid,)).fetchone()[0]==0
    assert c.get('/admin/registrations').status_code==200
    # A second pending account: resend rotates the token; old and expired links fail.
    post('/register',name='Test',surname='Pending',email='pending@example.test',phone_prefix='+44',phone='7700 900123',password='password123',confirm_password='password123',terms='yes',privacy='yes',terms_version=m.TERMS_VERSION,privacy_version=m.PRIVACY_VERSION,waiver_version=m.WAIVER_VERSION,waiver='yes')
    pending=con.execute("SELECT id FROM users WHERE email='pending@example.test'").fetchone()[0]
    assert con.execute('SELECT phone FROM users WHERE id=?',(pending,)).fetchone()[0]=='+447700900123'
    for prefix,number in [('+30','2100000000'),('+30','690000'),('+30','+306900000000'),('+999','6900000000'),('+30','69000000ab')]:
        assert post('/register',name='Test',surname='Invalid',email='invalid@example.test',phone_prefix=prefix,phone=number,password='password123',confirm_password='password123',terms='yes',privacy='yes',terms_version=m.TERMS_VERSION,privacy_version=m.PRIVACY_VERSION,waiver_version=m.WAIVER_VERSION,waiver='yes').status_code==302
        assert not con.execute("SELECT id FROM users WHERE email='invalid@example.test'").fetchone()
    old=con.execute('SELECT token_hash FROM registration_email_confirmations WHERE user_id=?',(pending,)).fetchone()[0]
    post('/register/resend-email',email='pending@example.test')
    assert con.execute('SELECT token_hash FROM registration_email_confirmations WHERE user_id=?',(pending,)).fetchone()[0]==old
    con.execute('UPDATE registration_email_confirmations SET issued_at=0 WHERE user_id=?',(pending,)); con.commit()
    post('/register/resend-email',email='pending@example.test')
    assert con.execute('SELECT token_hash FROM registration_email_confirmations WHERE user_id=?',(pending,)).fetchone()[0]!=old
    newest=max((root/'_local_data/mail-preview').glob('*.eml'),key=lambda f:f.stat().st_mtime_ns)
    body=BytesParser(policy=policy.default).parsebytes(newest.read_bytes()).get_body(preferencelist=('plain',)).get_content()
    expired=re.search(r'http://127.0.0.1:5000(/register/confirm-email/[\w-]+)',body)[1]
    con.execute('UPDATE registration_email_confirmations SET expires_at=0 WHERE user_id=?',(pending,)); con.commit()
    assert post(expired).status_code==400
    for _ in range(9): post('/register/resend-email',email='absent@example.test')
    assert post('/register/resend-email',email='absent@example.test').status_code==429
    # Known legacy minors still require guardian consent; no mass activation on restart.
    con.execute("UPDATE student_registrations SET birth_date='2015-01-01' WHERE user_id=?",(pending,))
    token=m.issue_confirmation(con,pending); con.commit()
    assert post('/register/confirm-email/'+token).status_code==200
    assert con.execute('SELECT active FROM users WHERE id=?',(pending,)).fetchone()[0]==0
    con.execute('UPDATE student_registrations SET guardian_approved_at=? WHERE user_id=?',('2026-10-16',pending))
    assert m.activate_verified_registration(con,pending)
    con.rollback()
    con.close()
    print('PASS: no DOB; zero credits; preview email; hashed token; GET safe; CSRF; verification; automatic activation; disabled-account protection; replay; resend cooldown/rotation; expiry; rate limit; student login; known-minor consent gate; default +30; international prefix formatting; invalid mobile rejection.')
