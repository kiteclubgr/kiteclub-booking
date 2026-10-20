import importlib.util,sys,tempfile,shutil
from pathlib import Path
source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder)/'app';shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','*.db-*','uploads','.local_secret_key','.git'))
 sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('local_launcher',root/'run_local.py');launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
 m=launcher.load_local_app();m.app.config['TESTING']=True;c=m.app.test_client();con=m.db();uid=con.execute("SELECT user_id FROM students ORDER BY user_id LIMIT 1").fetchone()[0]
 with c.session_transaction() as s:s['uid']=uid;s['_csrf_token']='home-qa'
 con.execute('UPDATE students SET credits=0 WHERE user_id=?',(uid,));con.commit();before=list(con.iterdump())
 r=c.get('/student/home');assert r.status_code==200;h=r.get_data(as_text=True);assert 'Δεν έχεις προγραμματισμένο μάθημα' in h and 'sh-book' in h and '0 <small>ώρες' in h and '0 / 18' in h;assert before==list(con.iterdump())

 for url in ['/student/home','/student','/student/profile','/student/profile/edit','/messages']:
  page=c.get(url);assert page.status_code==200
  assert page.text.count('class="kc-student-mobile-header"')==1
  assert 'class="kc-mobile-session-bar"' not in page.text

 for view in ['lessons','photos']:
  before=list(con.iterdump())
  page=c.get('/student/profile?view='+view);assert page.status_code==200
  assert before==list(con.iterdump())
  assert ('id="lessons"' in page.text)==(view=='lessons')
  assert ('id="photos"' in page.text)==(view=='photos')
  assert 'id="payments"' not in page.text and 'id="progress"' not in page.text and 'id="details"' not in page.text
  assert ('id="history"' in page.text)==(view=='lessons')

 con.execute('UPDATE students SET credits=2.5 WHERE user_id=?',(uid,));con.commit();h=c.get('/student/home').get_data(as_text=True);assert '2.5 <small>ώρες' in h and 'Οι ώρες σου είναι διαθέσιμες' in h
 assert c.post('/logout',data={'_csrf_token':'home-qa'}).status_code==302;assert c.get('/student/home').status_code==302
 print('PASS: zero and positive credits, real empty history and curriculum, read-only home render, booking links, POST logout and protected home')
