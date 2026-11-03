"""All active Students discover packages; checkout stays strictly sandbox-only."""
import importlib.util,os,shutil,sys,tempfile,re
from pathlib import Path
from unittest.mock import patch
source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'app';shutil.copytree(source,root,ignore=shutil.ignore_patterns('.git','_local_data','__pycache__','*.db','*.db-*','uploads','.local_secret_key','.venv'))
 sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('packages_launcher',root/'run_local.py');loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader);m=loader.load_local_app()
 m.app.config.update(TESTING=True,IS_KITECLUB_PRODUCTION=True)
 os.environ.update(STRIPE_ONLINE_TEST='1',STRIPE_TEST_ENABLED='0',PUBLIC_BASE_URL='https://booking.kiteclub.gr',STRIPE_SECRET_KEY='sk_test_fixture',STRIPE_WEBHOOK_SECRET='whsec_fixture',STRIPE_TEST_STUDENT_EMAILS='')
 con=m.db();members=[r[0] for r in con.execute('SELECT user_id FROM students ORDER BY user_id LIMIT 3')];sid=members[0]
 con.execute("UPDATE students SET lesson_type='private',group_id=NULL,credits=0 WHERE user_id=?",(sid,));con.commit()
 c=m.app.test_client()
 with c.session_transaction() as s:s['uid']=sid;s['_csrf_token']='packages-qa'
 with patch('socket.socket.connect',side_effect=AssertionError('No network')):
  h=c.get('/student/home');assert h.status_code==200 and h.text.count('href="/student/buy-hours"')>=3
  assert 'KiteClub v0.9.3' in h.text
  page=c.get('/student/buy-hours');assert page.status_code==200 and 'disabled' in page.text
  assert 'Οι πληρωμές TEST δεν είναι διαθέσιμες' in page.text
  with c.session_transaction() as s:assert not s.get('stripe_nonces')
  calls=[]
  def create(params,key):calls.append(params);return dict(id='cs_test_package_visibility',url='https://checkout.stripe.com/qa',livemode=False)
  m.app.extensions['stripe_test_gateway']['create']=create
  os.environ['STRIPE_TEST_ENABLED']='1'
  for size,kind in [(1,'private'),(2,'2p'),(3,'3p')]:
   group=None
   if size>1:
    group=con.execute("INSERT INTO student_groups(group_size,created_at) VALUES(?,'2026-11-03')",(size,)).lastrowid
   for member in members[:size]:con.execute('UPDATE students SET lesson_type=?,group_id=? WHERE user_id=?',(kind,group,member))
   con.commit()
   page=c.get('/student/buy-hours');assert page.status_code==200
   assert 'name="package_id"' in page.text and not re.search(r'<button[^>]*disabled',page.text)
  # A private package can enter TEST checkout for a student with no allowlisted email.
  con.execute("UPDATE students SET lesson_type='private',group_id=NULL WHERE user_id=?",(sid,));con.commit()
  page=c.get('/student/buy-hours');nonce=re.search(r'name="nonce" value="([^"]+)"',page.text)[1];pid=re.search(r'name="package_id" value="([^"]+)"',page.text)[1]
  before=(con.execute('SELECT credits FROM students WHERE user_id=?',(sid,)).fetchone()[0],con.execute('SELECT COUNT(*) FROM student_payments').fetchone()[0])
  assert c.post('/student/buy-hours',data={'_csrf_token':'packages-qa','nonce':nonce,'package_id':pid}).status_code==303
  assert len(calls)==1 and calls[0]['payment_intent_data']['metadata']['student_id']==str(sid)
  assert before==(con.execute('SELECT credits FROM students WHERE user_id=?',(sid,)).fetchone()[0],con.execute('SELECT COUNT(*) FROM student_payments').fetchone()[0])
  os.environ['STRIPE_SECRET_KEY']='sk_live_forbidden'
  assert c.post('/student/buy-hours',data={'_csrf_token':'packages-qa','nonce':nonce,'package_id':pid}).status_code==503
  assert len(calls)==1
 con.close()
print('PASS: permanent desktop/mobile/home links with disabled TEST feature; zero credits; v0.9.3; private/2P/3P catalog; any active Student TEST checkout; no early credits/payment; LIVE key rejected; no network')
