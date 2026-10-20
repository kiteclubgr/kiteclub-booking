"""Isolated database and signed fixtures; no network or real payment."""
import os,sys,shutil,tempfile,importlib.util,re,json,hmac,hashlib,time
from pathlib import Path
source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'app'; shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','.venv','uploads'))
 sys.path.insert(0,str(root)); spec=importlib.util.spec_from_file_location('launcher',root/'run_local.py'); launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
 os.environ.update(STRIPE_TEST_ENABLED='1',STRIPE_SECRET_KEY='sk_test_fixture',STRIPE_WEBHOOK_SECRET='whsec_fixture')
 m=launcher.load_local_app();m.app.config['TESTING']=True;c=m.app.test_client();con=m.db()
 uid=con.execute("SELECT id FROM users WHERE role='student' LIMIT 1").fetchone()[0]
 con.execute("UPDATE students SET lesson_type='private',group_id=NULL,credits=0 WHERE user_id=?",(uid,));con.commit()
 with c.session_transaction() as s:s['uid']=uid;s['_csrf_token']='test'
 assert c.post('/student/buy-hours').status_code==400
 page=c.get('/student/buy-hours');assert page.status_code==200,page.data
 nonce=re.search(r'name="nonce" value="([^"]+)"',page.text)[1];pid=con.execute("SELECT id FROM packages WHERE package_type='lesson' AND active=1 AND price>0 ORDER BY hours,id LIMIT 1").fetchone()[0]
 calls=[]
 def create(params,key):calls.append((params,key));return {'id':'cs_test_one','url':'https://checkout.stripe.com/test-fixture','livemode':False}
 m.app.extensions['stripe_test_gateway']['create']=create
 data={'_csrf_token':'test','nonce':nonce,'package_id':pid,'price':'0.01'}
 assert c.post('/student/buy-hours',data=data).status_code==303
 assert c.post('/student/buy-hours',data=data).status_code==303
 assert len(calls)==1
 assert "payment_method_types" not in calls[0][0], "Endive rejects payment_method_types"
 row=con.execute('SELECT * FROM stripe_test_orders').fetchone();before=con.execute('SELECT COUNT(*) FROM student_packages').fetchone()[0]
 status_url='/student/payments/'+row['id']
 before_status=list(con.iterdump())
 status=c.get(status_url);assert status.status_code==200 and 'Επιβεβαιώνουμε την πληρωμή σου' in status.text
 assert 'Συνέχεια πληρωμής' not in status.text
 assert c.get(status_url+'?format=json').json=={'state':'open','confirmed':False}
 assert c.get(status_url+'?format=json').headers['Cache-Control']=='no-store'
 cancelled=c.get(status_url+'?checkout=cancelled');assert 'data-poll-url=' not in cancelled.text
 assert before_status==list(con.iterdump())
 assert c.get('/student/payments/unknown?format=json').status_code==404
 assert con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]==0
 paid={'id':'cs_test_one','livemode':False,'mode':'payment','metadata':calls[0][0]['metadata'],'client_reference_id':row['id'],'payment_status':'paid','status':'complete','currency':'eur','amount_total':row['cents'],'amount_subtotal':row['cents'],'payment_intent':'pi_test_one','line_items':{'data':[{'quantity':1,'amount_total':row['cents']}],'has_more':False}}
 m.app.extensions['stripe_test_gateway']['retrieve']=lambda sid:paid
 def event(eid='evt_test',signature=True):
  body=json.dumps({'id':eid,'livemode':False,'type':'checkout.session.completed','data':{'object':{'id':'cs_test_one','metadata':calls[0][0]['metadata']}}}).encode();t=str(int(time.time()));digest=hmac.new(b'whsec_fixture',t.encode()+b'.'+body,hashlib.sha256).hexdigest()
  return c.post('/payments/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':f't={t},v1={digest if signature else "bad"}'})
 assert event(signature=False).status_code==400
 paid['payment_status']='unpaid';assert event().status_code==200
 assert con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]==0
 paid['payment_status']='paid';paid['amount_total']+=1;assert event().status_code==400;paid['amount_total']-=1
 assert event().status_code==200
 assert c.get(status_url+'?format=json').json=={'state':'paid','confirmed':True}
 success=c.get(status_url);assert 'Τα λέμε στην παραλία!' in success.text and 'data-poll-url=' not in success.text
 assert event().status_code==200 and event('evt_second').status_code==200
 assert con.execute('SELECT COUNT(*) FROM student_packages').fetchone()[0]==before+1
 assert con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]==row['hours']
 assert con.execute("SELECT COUNT(*),SUM(amount) FROM student_payments WHERE method='stripe_test'").fetchone()[:]==(1,row['cents']/100)
 assert con.execute("SELECT COUNT(*) FROM credit_ledger WHERE student_id=? AND note LIKE 'Stripe TEST%'",(uid,)).fetchone()[0]==1
 # Refund synchronization: authoritative retrieval, partial/full, replay, failure and used credits.
 refund={'id':'re_one','payment_intent':'pi_test_one','currency':'eur','amount':row['cents']//2,'status':'pending'}
 m.app.extensions['stripe_test_gateway']['refund']=lambda rid:dict(refund, id=rid)
 m.app.extensions['stripe_test_gateway']['intent']=lambda pi:{'id':pi,'livemode':False}
 def refund_event(rid='re_one',kind='refund.updated',valid=True):
  body=json.dumps({'id':'evt_refund','livemode':False,'type':kind,'data':{'object':{'id':rid,'amount':999999}}}).encode()
  t=str(int(time.time()));sig=hmac.new(b'whsec_fixture',t.encode()+b'.'+body,hashlib.sha256).hexdigest()
  return c.post('/payments/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':f't={t},v1={sig if valid else "bad"}'})
 def balance():return con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]
 assert refund_event(valid=False).status_code==400
 assert refund_event().status_code==200 and balance()==row['hours']
 refund['status']='succeeded'
 # A failed financial write must roll back the receipt and all balance changes.
 con.execute("CREATE TRIGGER qa_refund_fail BEFORE INSERT ON student_payments WHEN NEW.amount<0 BEGIN SELECT RAISE(ABORT,'refund rollback'); END");con.commit()
 import sqlite3
 try:refund_event();raise AssertionError('refund rollback not tested')
 except sqlite3.IntegrityError:pass
 assert balance()==row['hours']
 assert con.execute("SELECT applied_cents FROM stripe_test_refunds WHERE id='re_one'").fetchone()[0]==0
 con.execute('DROP TRIGGER qa_refund_fail');con.commit()
 assert refund_event().status_code==200 and balance()==row['hours']/2
 assert refund_event().status_code==200 and balance()==row['hours']/2
 assert con.execute("SELECT SUM(amount) FROM student_payments WHERE purchase_id=(SELECT purchase_id FROM stripe_test_orders WHERE id=?)",(row['id'],)).fetchone()[0]==row['cents']/200
 purchase_id=con.execute('SELECT purchase_id FROM stripe_test_orders WHERE id=?',(row['id'],)).fetchone()[0]
 assert con.execute('SELECT price-paid_amount FROM student_packages WHERE id=?',(purchase_id,)).fetchone()[0]==0
 from concurrent.futures import ThreadPoolExecutor
 with ThreadPoolExecutor(max_workers=2) as pool:
  assert list(pool.map(lambda _:refund_event('re_two').status_code,range(2)))==[200,200]
 assert balance()==0
 assert refund_event('re_two').status_code==200 and balance()==0
 assert con.execute('SELECT price,paid_amount,hours_total,hours_remaining FROM student_packages WHERE id=?',(purchase_id,)).fetchone()[:]==(0,0,0,0)
 # Refunded labels in Admin/Student, including when TEST is disabled. Rendering is read-only.
 snapshot=list(con.iterdump())
 with c.session_transaction() as sess:sess['uid']=con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
 profile=c.get('/admin/students/'+str(uid));assert profile.status_code==200
 assert 'Επιστράφηκε' in profile.text and 'Ώρες επιστραφείσες' in profile.text
 assert ('/admin/package-purchases/'+str(purchase_id)+'/cancel') not in profile.text
 assert c.get('/admin/packages').status_code==200
 with c.session_transaction() as sess:sess['uid']=uid
 student=c.get('/student/profile');assert student.status_code==200 and 'Επιστράφηκε' in student.text
 os.environ['STRIPE_TEST_ENABLED']='0'
 assert 'Επιστράφηκε' in c.get('/student/profile').text
 os.environ['STRIPE_TEST_ENABLED']='1'
 assert snapshot==list(con.iterdump()), 'Display must not change balances or receipts'
 # A duplicate paid webhook cannot regrant the original package.
 assert event().status_code==200 and balance()==0
 refund['status']='failed'
 assert refund_event('re_two','refund.failed').status_code==200 and balance()==row['hours']/2
 assert refund_event('re_one','refund.failed').status_code==200 and balance()==row['hours']
 # Unknown e-shop payment is ignored, and mismatched currency is rejected.
 refund['payment_intent']='pi_other';refund['status']='succeeded'
 assert refund_event('re_other').status_code==200 and balance()==row['hours']
 refund['payment_intent']='pi_test_one';refund['currency']='usd'
 assert refund_event('re_bad').status_code==400 and balance()==row['hours']
 refund['currency']='eur'
 # Reserved/used hours are never removed silently. Refund money is still recorded.
 con.execute('UPDATE students SET credits=0 WHERE user_id=?',(uid,))
 con.execute('UPDATE student_packages SET hours_remaining=0 WHERE id=?',(purchase_id,));con.commit()
 assert refund_event('re_used').status_code==200 and balance()==0
 assert con.execute('SELECT review FROM stripe_test_refund_totals WHERE order_id=?',(row['id'],)).fetchone()[0]
 assert c.get('/admin/stripe-refunds').status_code==403
 admin=con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
 with c.session_transaction() as sess:sess['uid']=admin;sess['_csrf_token']='test'
 assert c.get('/admin/stripe-refunds').status_code==200
 assert c.post('/admin/stripe-refunds/re_used/sync').status_code==400
 assert c.post('/admin/stripe-refunds/re_used/sync',data={'_csrf_token':'test'}).status_code==303
 assert c.get('/admin/finance').status_code==200
 assert c.get('/admin/reports').status_code==200
 # Return the fixture to its initial accounting state for the existing suite.
 refund['status']='failed';assert refund_event('re_used').status_code==200
 con.execute('UPDATE students SET credits=? WHERE user_id=?',(row['hours'],uid))
 con.execute('UPDATE student_packages SET hours_remaining=? WHERE id=?',(row['hours'],purchase_id));con.commit()
 with c.session_transaction() as sess:sess['uid']=uid;sess['_csrf_token']='test'
 assert con.execute('SELECT price,paid_amount,hours_total FROM student_packages WHERE id=?',(purchase_id,)).fetchone()[:]==(row['cents']/100,row['cents']/100,row['hours'])
 print('PASS: signed refund partial/full/replay, pending, failed reversal, unrelated payment, currency, used-credit review, Admin access/CSRF, finance/reports')
 # Full 2P/3P groups are required, and cannot buy a private package.
 members=[r[0] for r in con.execute("SELECT id FROM users WHERE role='student' AND active=1 LIMIT 3")]
 assert len(members)==3
 for size in (2,3):
  kind=str(size)+'p';gid=con.execute("INSERT INTO student_groups(group_size,created_at) VALUES(?,?)",(size,'2026-10-18')).lastrowid
  for member in members[:size]:con.execute('UPDATE students SET lesson_type=?,group_id=? WHERE user_id=?',(kind,gid,member))
  con.commit()
  page=c.get('/student/buy-hours');assert page.status_code==200
  nonce2=re.search(r'name="nonce" value="([^"]+)"',page.text)[1]
  assert c.post('/student/buy-hours',data={'_csrf_token':'test','nonce':nonce2,'package_id':pid}).status_code==400
  group_pid=con.execute('SELECT id FROM packages WHERE active=1 AND package_type=? AND price>0 LIMIT 1',('group_'+kind,)).fetchone()[0]
  created=[]
  def group_create(params,key):
   created.append(params);return {'id':'cs_test_'+kind,'url':'https://checkout.stripe.com/test-'+kind,'livemode':False}
  m.app.extensions['stripe_test_gateway']['create']=group_create
  assert c.post('/student/buy-hours',data={'_csrf_token':'test','nonce':nonce2,'package_id':group_pid}).status_code==303
  assert created
  # Removing a required member blocks new checkout, even for a valid catalogue ID.
  con.execute('UPDATE students SET group_id=NULL WHERE user_id=?',(members[size-1],));con.commit()
  page=c.get('/student/buy-hours');assert 'name="package_id"' not in page.text
  nonce3=re.search(r'name="nonce" value="([^"]+)"',page.text) if 'name="nonce"' in page.text else None
  with c.session_transaction() as sess: latest=sess['stripe_nonces'][-1]
  assert c.post('/student/buy-hours',data={'_csrf_token':'test','nonce':latest,'package_id':group_pid}).status_code==400
 # Failure during activation rolls the complete transaction back; retry succeeds.
 import stripe_payments
 original=m._activate_student_purchase
 # The fulfillment closure captures activate; cause SQL ledger failure to verify rollback.
 con.execute("CREATE TRIGGER qa_fail BEFORE INSERT ON credit_ledger BEGIN SELECT RAISE(ABORT,'qa rollback'); END");con.commit()
 target=con.execute("SELECT * FROM stripe_test_orders WHERE checkout_id='cs_test_2p'").fetchone()
 paid.update(id='cs_test_2p',metadata={'app':'kiteclub_booking','order_id':target['id'],'student_id':str(uid)},client_reference_id=target['id'],amount_total=target['cents'],amount_subtotal=target['cents'],payment_intent='pi_test_2p',line_items={'data':[{'quantity':1,'amount_total':target['cents']}],'has_more':False})
 calls[0][0]['metadata']=paid['metadata']
 def group_event():
  body=json.dumps({'id':'evt_group','livemode':False,'type':'checkout.session.completed','data':{'object':{'id':paid['id'],'metadata':paid['metadata']}}}).encode();t=str(int(time.time()));digest=hmac.new(b'whsec_fixture',t.encode()+b'.'+body,hashlib.sha256).hexdigest()
  return m.app.test_client().post('/payments/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':f't={t},v1={digest}'})
 import sqlite3
 try:group_event();raise AssertionError('rollback not tested')
 except sqlite3.IntegrityError:pass
 assert con.execute('SELECT COUNT(*) FROM student_packages').fetchone()[0]==before+1
 con.execute('DROP TRIGGER qa_fail');con.commit()
 from concurrent.futures import ThreadPoolExecutor
 with ThreadPoolExecutor(max_workers=2) as pool:
  assert list(pool.map(lambda _:group_event().status_code,range(2)))==[200,200]
 assert con.execute('SELECT COUNT(*) FROM student_packages').fetchone()[0]==before+2
 target3=con.execute("SELECT * FROM stripe_test_orders WHERE checkout_id='cs_test_3p'").fetchone()
 others_before={x:con.execute('SELECT credits FROM students WHERE user_id=?',(x,)).fetchone()[0] for x in members if x!=uid}
 paid.update(id='cs_test_3p',metadata={'app':'kiteclub_booking','order_id':target3['id'],'student_id':str(uid)},client_reference_id=target3['id'],amount_total=target3['cents'],amount_subtotal=target3['cents'],payment_intent='pi_test_3p',line_items={'data':[{'quantity':1,'amount_total':target3['cents']}],'has_more':False})
 paid.update(payment_status='unpaid',status='expired');assert group_event().status_code==200
 assert con.execute('SELECT COUNT(*) FROM student_packages').fetchone()[0]==before+2
 paid.update(payment_status='paid',status='complete');assert group_event().status_code==200
 assert con.execute('SELECT COUNT(*) FROM student_packages').fetchone()[0]==before+3
 assert con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]==row['hours']+target['hours']+target3['hours']
 for x,balance in others_before.items():assert con.execute('SELECT credits FROM students WHERE user_id=?',(x,)).fetchone()[0]==balance
 paid.update(payment_status='unpaid',status='expired');assert group_event().status_code==200
 assert con.execute('SELECT state FROM stripe_test_orders WHERE id=?',(target3['id'],)).fetchone()[0]=='paid'
 os.environ['STRIPE_TEST_ENABLED']='0';assert c.get('/student/buy-hours').status_code==503
 os.environ['STRIPE_TEST_ENABLED']='1'
 m.app.config['IS_KITECLUB_PRODUCTION']=True
 # The launch-time local guard is supplemented by current production config.
 assert c.get('/student/buy-hours').status_code==503
 m.app.config['IS_KITECLUB_PRODUCTION']=False
 with c.session_transaction() as s:s['uid']=999999
 assert c.get('/student/payments/'+row['id']).status_code in (403,404)
 os.environ['STRIPE_SECRET_KEY']='sk_live_not_allowed';assert c.get('/student/buy-hours').status_code==503
 con.close();print('PASS: CSRF, server price, duplicate checkout, pending/invalid/signed webhook, replay, exact credits/payment, ownership, live-key rejection, 2P/3P eligibility, transaction rollback and retry')
