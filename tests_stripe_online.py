"""Online configuration/allowlist checks in an isolated SQLite file; no network."""
import os,sqlite3,tempfile,json,time,hmac,hashlib
from pathlib import Path
from flask import Flask
from stripe_payments import setup_stripe_payments
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)/'fixture.db'
 def db():
  c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
 c=db();c.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT,role TEXT,active INTEGER);
 CREATE TABLE students(user_id INTEGER,lesson_type TEXT,group_id INTEGER);
 CREATE TABLE packages(id INTEGER PRIMARY KEY,name TEXT,active INTEGER,package_type TEXT,hours REAL,price REAL);
 INSERT INTO users VALUES(1,'qa-stripe@kiteclub.gr','student',1),(2,'real@example.com','student',1);
 INSERT INTO students VALUES(1,'private',NULL),(2,'private',NULL);
 INSERT INTO packages VALUES(1,'1h',1,'lesson',1,60);""");c.commit();c.close()
 os.environ.update(STRIPE_ONLINE_TEST='1',PUBLIC_BASE_URL='https://booking.kiteclub.gr',STRIPE_TEST_STUDENT_EMAILS='qa-stripe@kiteclub.gr',STRIPE_TEST_ENABLED='1',STRIPE_SECRET_KEY='sk_test_fixture',STRIPE_WEBHOOK_SECRET='whsec_fixture')
 app=Flask(__name__);app.config.update(TESTING=True,SECRET_KEY='x'*32,IS_KITECLUB_PRODUCTION=True)
 user={'id':1,'role':'student'}
 setup_stripe_payments(app,db,lambda:user,lambda *x:None,Path(tmp)/'online-volume',Path(tmp)/'app')
 client=app.test_client()
 with client.session_transaction() as s:s['stripe_nonces']=['fixture']
 calls=[]
 def create(params,key):calls.append(params);return {'id':'cs_fixture','url':'https://checkout.stripe.com/fixture','livemode':False}
 app.extensions['stripe_test_gateway']['create']=create
 user['id']=2
 assert client.post('/student/buy-hours',data={'nonce':'fixture','package_id':'1'}).status_code==403
 user['id']=1
 assert client.post('/student/buy-hours',data={'nonce':'fixture','package_id':'1'}).status_code==303
 assert calls[0]['success_url'].startswith('https://booking.kiteclub.gr/student/payments/')
 assert calls[0]['cancel_url'].startswith('https://booking.kiteclub.gr/student/payments/')
 assert calls[0]['payment_intent_data']['metadata']['student_id']=='1'
 os.environ['STRIPE_SECRET_KEY']='sk_live_forbidden'
 assert client.post('/student/buy-hours',data={'nonce':'fixture','package_id':'1'}).status_code==503
 os.environ['STRIPE_SECRET_KEY']='sk_test_fixture'
 os.environ['STRIPE_TEST_STUDENT_EMAILS']=''
 assert client.post('/student/buy-hours',data={'nonce':'fixture','package_id':'1'}).status_code==503
 os.environ['STRIPE_TEST_STUDENT_EMAILS']='qa-stripe@kiteclub.gr'
 os.environ['PUBLIC_BASE_URL']='https://attacker.example'
 assert client.post('/student/buy-hours',data={'nonce':'fixture','package_id':'1'}).status_code==503
 os.environ['PUBLIC_BASE_URL']='https://booking.kiteclub.gr'
 os.environ['STRIPE_ONLINE_TEST']='0'
 assert client.post('/student/buy-hours',data={'nonce':'fixture','package_id':'1'}).status_code==503
 print('PASS: online TEST allowlist, exact HTTPS return URLs, PaymentIntent metadata, live-key rejection, missing allowlist, wrong origin, online flag off')
