"""Private 1h/2h/8h choice must survive navigation, auth and TEST checkout."""
import importlib.util, os, shutil, sys, tempfile, re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch
source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'app'
 shutil.copytree(source,root,ignore=shutil.ignore_patterns('.git','_local_data','__pycache__','*.db','*.db-*','uploads','.local_secret_key','.venv'))
 sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('private_pages_launcher',root/'run_local.py');launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher);m=launcher.load_local_app()
 m.app.config.update(TESTING=True,IS_KITECLUB_PRODUCTION=True)
 os.environ.update(STRIPE_ONLINE_TEST='1',STRIPE_TEST_ENABLED='1',PUBLIC_BASE_URL='https://booking.kiteclub.gr',STRIPE_SECRET_KEY='sk_test_fixture',STRIPE_WEBHOOK_SECRET='whsec_fixture')
 con=m.db();sid=con.execute('SELECT user_id FROM students ORDER BY user_id LIMIT 1').fetchone()[0]
 con.execute("UPDATE students SET lesson_type='private',group_id=NULL WHERE user_id=?",(sid,));con.commit()
 email=con.execute('SELECT email FROM users WHERE id=?',(sid,)).fetchone()[0]
 before_credits=con.execute('SELECT credits FROM students WHERE user_id=?',(sid,)).fetchone()[0]
 calls=[]
 def create(params,key):
  calls.append(params);return dict(id='cs_test_private_'+str(len(calls)),url='https://checkout.stripe.com/test',livemode=False)
 m.app.extensions['stripe_test_gateway']['create']=create
 with patch('socket.socket.connect',side_effect=AssertionError('External network forbidden')):
  for h in (1,2,8):
   slug=f'private-{h}h'
   package=con.execute("SELECT * FROM packages WHERE active=1 AND package_type='lesson' AND hours=? ORDER BY id LIMIT 1",(h,)).fetchone()
   assert package is not None
   for language,prefix in [('el',''),('en','/en')]:
    anonymous=m.app.test_client();r=anonymous.get(prefix+'/packages/'+slug)
    assert r.status_code==200,(h,language,r.status_code)
    assert f'{package["price"]:g}€' in r.text
    assert ('1 ώρα kitesurf' if language=='el' else '1 hour of kitesurfing') in r.text if h==1 else True
    assert 'package='+slug in r.text
    assert f'href="{prefix}/packages/private-1h"' in r.text and f'href="{prefix}/packages/private-2h"' in r.text
   # Session persistence across registration/email verification context.
   c=m.app.test_client();c.get('/?package='+slug+'&lang=en')
   with c.session_transaction() as s:token=s['_csrf_token']
   r=c.post('/?lang=en',data={'_csrf_token':token,'email':email,'password':'student123'})
   assert r.status_code==302 and urlsplit(r.location).path=='/student/package-review'
   assert parse_qs(urlsplit(r.location).query).get('package',['private-8h'])==[slug]
   with c.session_transaction() as s:assert 'registration_package' not in s
   r=c.get(r.location);assert r.status_code==200
   assert f'name="package_id" value="{package["id"]}"' in r.text
   assert f'package={slug}' in r.text
   with c.session_transaction() as s:
    s['registration_package']=slug
   with c:
    c.get('/student/home')
    with m.app.test_request_context('/'):
     from flask import session
     session['registration_package']=slug
     m.app.extensions['purchase_save_context'](con,sid);con.commit();session.pop('registration_package')
     m.app.extensions['purchase_restore_context'](con,sid)
     assert session['registration_package']==slug
   nonce=re.search(r'name="nonce" value="([^"]+)"',r.text)[1]
   with c.session_transaction() as s:token=s['_csrf_token']
   assert c.post('/student/buy-hours',data={'_csrf_token':token,'nonce':nonce,'package_id':package['id']}).status_code==303
   assert calls[-1]['line_items'][0]['price_data']['unit_amount']==round(package['price']*100)
   assert calls[-1]['payment_intent_data']['metadata']['student_id']==str(sid)
   assert c.get('/',follow_redirects=True).request.path=='/student/home'
  assert con.execute('SELECT credits FROM students WHERE user_id=?',(sid,)).fetchone()[0]==before_credits
  assert con.execute('SELECT COUNT(*) FROM student_payments').fetchone()[0]==0
  c=m.app.test_client()
  for path in ['/packages/private-3h','/packages/private-0h','/packages/2p-1h','/student/package-review?package=2p-1h']:
   assert c.get(path).status_code==404,path
  con.execute("UPDATE packages SET active=0 WHERE package_type='lesson' AND hours=1");con.commit()
  assert c.get('/packages/private-1h').status_code==404
 con.close()
print('PASS: Private 1h/2h/8h EN/EL pages; DB prices; links; login and email context; selected review/TEST checkout amount; no early credits/payment; unknown/inactive packages rejected; no network')
