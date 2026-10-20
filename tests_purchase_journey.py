"""Full signup -> email -> second browser -> login -> review, no network."""
import os, sys, tempfile, shutil, importlib.util, re
from pathlib import Path

source=Path(__file__).parent
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'app'
 shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','uploads','.venv'))
 sys.path.insert(0,str(root))
 os.environ.update(STRIPE_TEST_ENABLED='1',STRIPE_SECRET_KEY='sk_test_fixture',STRIPE_WEBHOOK_SECRET='whsec_fixture')
 spec=importlib.util.spec_from_file_location('launcher',root/'run_local.py');launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
 m=launcher.load_local_app();m.app.config['TESTING']=True
 import registration_email
 sent=[];registration_email.deliver_message=lambda message,**kwargs:sent.append(message) or 'sent'
 c=m.app.test_client()
 page=c.get('/register?lang=en&package=private-8h').get_data(as_text=True)
 def hidden(page,name):
  return re.search(r'name="'+name+r'" value="([^"]*)"',page).group(1)
 form={k:hidden(page,k) for k in ['_csrf_token','waiver_version','terms_version','privacy_version']}
 form.update(name='Journey',surname='QA',email='journey-qa@example.com',phone_prefix='+30',phone='6912345678',password='JourneyTest123!',confirm_password='JourneyTest123!',terms='yes',privacy='yes',waiver='yes')
 r=c.post('/register?lang=en',data=form)
 assert r.status_code==303,r.data
 assert '/register/check-email' in r.location
 assert b'380' in c.get(r.location).data
 assert len(sent)==1 and sent[0]['Subject']=='KiteClub — Activate your account'
 message=sent[0].get_body(preferencelist=('plain',)).get_content()
 assert 'Verify your email' in message
 link=re.search(r'http[^\s]+/register/confirm-email/[^\s]+',message).group(0)
 from urllib.parse import urlsplit
 parts=urlsplit(link);path=parts.path+'?'+parts.query
 other=m.app.test_client()
 view=other.get(path);assert view.status_code==200
 con=m.db();uid=con.execute("SELECT id FROM users WHERE email='journey-qa@example.com'").fetchone()[0]
 assert con.execute('SELECT active FROM users WHERE id=?',(uid,)).fetchone()[0]==0;con.close()
 token=hidden(view.get_data(as_text=True),'_csrf_token')
 activated=other.post(path,data={'_csrf_token':token});assert activated.status_code==200
 assert b'Your email is verified' in activated.data
 assert other.post(path,data={'_csrf_token':token}).status_code==400
 login_response=other.get('/?lang=en')
 assert login_response.status_code==200,(login_response.status_code,login_response.location)
 login=login_response.get_data(as_text=True)
 result=other.post('/?lang=en',data={'_csrf_token':hidden(login,'_csrf_token'),'email':form['email'],'password':form['password']})
 assert result.status_code==302 and '/student/package-review' in result.location,result.location
 review=other.get(result.location);assert review.status_code==200
 text=review.get_data(as_text=True);assert '380.00€' in text and 'Review your purchase' in text
 form2={k:hidden(text,k) for k in ['_csrf_token','nonce','package_id']}
 calls=[]
 def checkout(params,key):
  calls.append(params);return {'livemode':False,'id':'cs_test_journey','url':'https://checkout.stripe.com/c/pay/test-journey'}
 m.app.extensions['stripe_test_gateway']['create']=checkout
 con=m.db();con.execute('UPDATE packages SET price=381 WHERE id=?',(form2['package_id'],));con.commit();con.close()
 assert other.post('/student/buy-hours',data=form2).status_code==409
 assert not calls
 con=m.db();con.execute('UPDATE packages SET price=380 WHERE id=?',(form2['package_id'],));con.commit();con.close()
 assert other.post('/student/buy-hours',data=form2).status_code==303
 assert calls[0]['line_items'][0]['price_data']['unit_amount']==38000
 assert calls[0]['locale']=='en'
 assert other.post('/student/buy-hours',data=form2).status_code==303 and len(calls)==1
 con=m.db();assert con.execute('SELECT credits FROM students WHERE user_id=?',(uid,)).fetchone()[0]==0
 assert con.execute('SELECT COUNT(*) FROM student_packages WHERE student_id=?',(uid,)).fetchone()[0]==0;con.close()
 # Preview can never initiate checkout, and is safe without an account.
 preview=m.app.test_client().get('/packages/private-8h/review-preview?lang=en')
 assert preview.status_code==200 and b'disabled' in preview.data
 # The Greek path keeps Greek email and uses the same required legal fields.
 greek=m.app.test_client()
 page=greek.get('/register?lang=el&package=private-8h').get_data(as_text=True)
 greek_form=dict(form,email='journey-el@example.com')
 greek_form.update({k:hidden(page,k) for k in ['_csrf_token','waiver_version','terms_version','privacy_version']})
 assert greek.post('/register?lang=el',data=greek_form).status_code==303
 assert len(sent)==2 and sent[-1]['Subject']=='KiteClub — Ενεργοποίηση λογαριασμού'
 # Login must rotate CSRF; English error messages remain understandable.
 bad=m.app.test_client();login=bad.get('/?lang=en').get_data(as_text=True)
 response=bad.post('/?lang=en',data={'_csrf_token':hidden(login,'_csrf_token'),'email':'missing@example.com','password':'wrong'})
 assert b'Incorrect email or password' in response.data
 resend=bad.get('/register/resend-email?lang=en');assert b'Registration email' in resend.data
 assert bad.post('/register/resend-email?lang=en',data={'email':'unknown@example.com'}).status_code==400
 print('PASS: English signup/email, cross-device confirmation, one-use token, login preserves package, authoritative price conflict, Stripe TEST locale, double submit, no premature credits, safe preview')
