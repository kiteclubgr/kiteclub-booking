"""Regression: pending package intent must never trap an authenticated portal user."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch

source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)/'app'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('.git','_local_data','__pycache__','*.db','*.db-*','uploads','.local_secret_key','.venv'))
    sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('navigation_launcher',root/'run_local.py')
    launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher);m=launcher.load_local_app()
    m.app.config.update(TESTING=True,IS_KITECLUB_PRODUCTION=True)
    os.environ.update(STRIPE_TEST_ENABLED='1',STRIPE_ONLINE_TEST='1',PUBLIC_BASE_URL='https://booking.kiteclub.gr',STRIPE_SECRET_KEY='sk_test_fixture',STRIPE_WEBHOOK_SECRET='whsec_fixture',STRIPE_TEST_STUDENT_EMAILS='different@example.test')
    con=m.db();sid=con.execute('SELECT user_id FROM students ORDER BY user_id LIMIT 1').fetchone()[0]
    con.execute("UPDATE students SET lesson_type='private',group_id=NULL WHERE user_id=?",(sid,));con.commit()
    email=con.execute('SELECT email FROM users WHERE id=?',(sid,)).fetchone()[0]
    before=list(con.iterdump())
    with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
        c=m.app.test_client()
        with c.session_transaction() as s:s.update(uid=sid,registration_package='private-8h',purchase_language='en')
        # Existing sessions with stale purchase intent still reach the portal from root.
        r=c.get('/',follow_redirects=True)
        assert r.status_code==200 and r.request.path=='/student/home',r.request.path
        for language,prefix in [('el',''),('en','/en')]:
            page=c.get(prefix+'/packages/private-8h').text
            assert 'href="/home"' in page
            assert ('Το portal μου' if language=='el' else 'My portal') in page
            assert ('Προβολή πακέτου' if language=='el' else 'Review package') in page
            assert ('Δημιουργία λογαριασμού' if language=='el' else 'Create an account') not in page
        # Explicit purchase links still work and are consumed only once.
        r=c.get('/?package=private-8h&lang=en')
        assert r.status_code==302 and urlsplit(r.location).path=='/student/package-review'
        with c.session_transaction() as s:assert 'registration_package' not in s
        page=c.get(r.location);assert page.status_code==200
        assert 'Go to my student portal' in page.text and 'href="/student/home"' in page.text
        r=c.get('/',follow_redirects=True);assert r.request.path=='/student/home'
        # A fresh password login honors the selected package once, then root escapes.
        fresh=m.app.test_client();fresh.get('/?package=private-8h&lang=en')
        with fresh.session_transaction() as s:token=s['_csrf_token']
        r=fresh.post('/?lang=en',data={'_csrf_token':token,'email':email,'password':'student123'})
        assert r.status_code==302 and urlsplit(r.location).path=='/student/package-review'
        with fresh.session_transaction() as s:assert 'registration_package' not in s
        assert fresh.get('/',follow_redirects=True).request.path=='/student/home'
        # Anonymous and non-student visitors retain appropriate navigation.
        anon=m.app.test_client();assert anon.get('/').status_code==200
        assert 'Log in' in anon.get('/en/packages/private-8h').text
        assert 'My portal' not in anon.get('/en/packages/private-8h').text
        for role in ('admin','instructor'):
            other=m.app.test_client()
            with other.session_transaction() as s:
                s['uid']=con.execute('SELECT id FROM users WHERE role=? LIMIT 1',(role,)).fetchone()[0]
                s['registration_package']='private-8h'
            r=other.get('/');assert r.status_code==302 and urlsplit(r.location).path=='/home'
        assert before==list(con.iterdump())
    con.close()
print('PASS: stale purchase session -> root -> Student Home; EN/EL authenticated package links; explicit and fresh-login purchase intent once; review portal escape; anonymous/Admin/Instructor routing; DB unchanged; no network')
