"""Production-style package review permissions, isolated DB and no provider calls."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/'app'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('.git','_local_data','__pycache__','*.db','*.db-*','uploads','.local_secret_key','.venv'))
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location('review_launcher',root/'run_local.py')
    launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    m=launcher.load_local_app();m.app.config.update(TESTING=True,IS_KITECLUB_PRODUCTION=True)
    os.environ.update(STRIPE_ONLINE_TEST='1',STRIPE_TEST_ENABLED='0',PUBLIC_BASE_URL='https://booking.kiteclub.gr',STRIPE_SECRET_KEY='sk_test_fixture',STRIPE_WEBHOOK_SECRET='whsec_fixture',STRIPE_TEST_STUDENT_EMAILS='allowed@example.test')
    con=m.db();sid=con.execute('SELECT user_id FROM students ORDER BY user_id LIMIT 1').fetchone()[0]
    con.execute("UPDATE users SET email='new-student@example.test' WHERE id=?",(sid,))
    con.execute("UPDATE students SET lesson_type='private',group_id=NULL WHERE user_id=?",(sid,));con.commit()
    calls=[]
    m.app.extensions['stripe_test_gateway']['create']=lambda *args: calls.append(args)
    with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
        anonymous=m.app.test_client();r=anonymous.get('/student/package-review?lang=en')
        assert r.status_code==302 and urlsplit(r.location).path=='/'
        assert parse_qs(urlsplit(r.location).query)=={'package':['private-8h'],'lang':['en']}
        c=m.app.test_client()
        with c.session_transaction() as s:s.update(_csrf_token='qa-review',registration_package='private-8h',purchase_language='en')
        r=c.post('/?lang=en',data={'_csrf_token':'qa-review','email':'new-student@example.test','password':'student123'})
        assert r.status_code==302 and urlsplit(r.location).path=='/student/package-review'
        before=list(con.iterdump())
        r=c.get(r.location);assert r.status_code==200 and r.headers['Cache-Control']=='no-store'
        assert b'TEST payments are currently disabled' in r.data and re.search(rb'<button[^>]*disabled',r.data)
        with c.session_transaction() as s:
            assert not s.get('stripe_nonces') and not s.get('purchase_reviews')
            token=s['_csrf_token'];s['stripe_nonces']=['forged']
        pid=con.execute("SELECT id FROM packages WHERE active=1 AND package_type='lesson' AND hours=8 LIMIT 1").fetchone()[0]
        assert c.post('/student/buy-hours',data={'_csrf_token':token,'nonce':'forged','package_id':pid}).status_code==503
        assert list(con.iterdump())==before and not calls
        assert 'Δεν έγινε καμία χρέωση' in c.get('/student/package-review?lang=el').text
        os.environ['STRIPE_TEST_ENABLED']='1'
        os.environ['STRIPE_TEST_STUDENT_EMAILS']=''
        r=c.get('/student/package-review?lang=en');assert r.status_code==200
        assert not re.search(rb'<button[^>]*disabled',r.data)
        with c.session_transaction() as s:assert s['purchase_reviews'] and s['stripe_nonces']
        os.environ['STRIPE_TEST_ENABLED']='0'
        r=c.get('/student/package-review?lang=en');assert r.status_code==200 and b'TEST payments are currently disabled' in r.data
        assert c.post('/student/buy-hours',data={'_csrf_token':token,'nonce':'forged','package_id':pid}).status_code==503
        admin=m.app.test_client()
        with admin.session_transaction() as s:s['uid']=con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        r=admin.get('/student/package-review?lang=en');assert r.status_code==302 and urlsplit(r.location).path=='/home'
        con.execute("UPDATE students SET lesson_type='2p',group_id=NULL WHERE user_id=?",(sid,));con.commit()
        r=c.get('/student/package-review?lang=en');assert r.status_code==302 and urlsplit(r.location).path=='/student/home'
        assert not calls
    con.close()
print('PASS: real login -> restricted review 200; anonymous login context; EN/EL notice; no forbidden nonce; checkout disabled-mode guard; allowed account review; Admin/group redirects; no DB mutation or network/payment')
