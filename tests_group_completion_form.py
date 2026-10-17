"""Offline real edit/cancel/complete routes, isolated seed and package ledgers."""
import importlib.util, shutil, sys, tempfile, json
from pathlib import Path
source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder)/'app';shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','*.db-*','uploads','.local_secret_key','.git'))
 sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('launcher',root/'run_local.py');launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
 m=launcher.load_local_app();m.app.config['TESTING']=True;c=m.app.test_client();con=m.db()
 admin=dict(con.execute("SELECT * FROM users WHERE role='admin'").fetchone());iid=con.execute('SELECT user_id FROM instructors ORDER BY user_id').fetchone()[0];other_iid=con.execute('SELECT user_id FROM instructors ORDER BY user_id LIMIT 1 OFFSET 1').fetchone()[0]
 students=[r[0] for r in con.execute('SELECT user_id FROM students ORDER BY user_id')];spot=con.execute('SELECT id FROM spots LIMIT 1').fetchone()[0];day='2026-10-17'
 def actor(uid):
  with c.session_transaction() as s:s['uid']=uid;s['_csrf_token']='merge-qa-token'
 def post(path,**data):return c.post(path,data={'_csrf_token':'merge-qa-token',**data})
 def setup(size=1,reverse=False):
  for t in ('booking_merges','booking_audit','booking_slots','booking_participants','package_usage','credit_ledger','lesson_payments','lesson_debts','instructor_hours','bookings','slots','day_columns','day_hours','day_spots','student_packages','student_groups'):
   con.execute(f'DELETE FROM {t}')
  con.execute("UPDATE students SET credits=0,lesson_type='private',group_id=NULL")
  members=students[:size];kind={1:'private',2:'2p',3:'3p'}[size]
  if size>1:
   gid=con.execute('INSERT INTO student_groups(group_size,created_at) VALUES(?,?)',(size,day)).lastrowid
   con.executemany('UPDATE students SET lesson_type=?,group_id=? WHERE user_id=?',[(kind,gid,s) for s in members])
  for sid in members:
   con.execute('UPDATE students SET credits=2 WHERE user_id=?',(sid,))
   con.execute("INSERT INTO credit_ledger(student_id,amount,kind,created_at) VALUES(?,2,'package_activation',?)",(sid,day))
   con.execute("INSERT INTO student_packages(student_id,package_name,hours_total,hours_remaining,price,payment_status,purchased_at,package_type,credits_activated) VALUES(?,'QA',2,2,110,'unpaid',?,'lesson',1)",(sid,day))
  for col,inst in enumerate((iid,other_iid),1):con.execute('INSERT INTO day_columns(lesson_date,column_no,instructor_id) VALUES(?,?,?)',(day,col,inst))
  slots={}
  for inst in (iid,other_iid):
   for time in ('13:00','14:00'):
    slots[inst,time]=con.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES(?,?,?,?,'open')",(day,time,inst,spot)).lastrowid
  bids=[];times=['14:00','13:00'] if reverse else ['13:00','14:00']
  for n,time in enumerate(times):
   inst=iid if n==0 else other_iid;slot=slots[inst,time]
   bid=con.execute("INSERT INTO bookings(slot_id,student_id,duration,status,payment_status,group_lesson_type,created_at) VALUES(?,?,1,'confirmed','credit',?,?)",(slot,members[0],kind,day)).lastrowid
   m._charge_booking_participants(con,bid,members,1)
   con.execute('INSERT INTO booking_slots VALUES(?,?)',(bid,slot));con.execute("UPDATE slots SET status='booked' WHERE id=?",(slot,))
   m.log_booking_audit(con,bid,'created','Original one-hour booking',admin['id'],'admin')
   bids.append(bid)
  con.commit();actor(admin['id']);return members,bids,slots,times
 def money():
  return ([tuple(r) for r in con.execute('SELECT user_id,credits FROM students ORDER BY user_id')],
          [tuple(r) for r in con.execute('SELECT id,amount FROM credit_ledger ORDER BY id')],
          [tuple(r) for r in con.execute('SELECT id,hours_remaining,price,paid_amount FROM student_packages ORDER BY id')],
          con.execute('SELECT COUNT(*) FROM student_payments').fetchone()[0])

 m.send_email=lambda *args,**kwargs: None
 for size in (2,3):
  members,bids,slots,times=setup(size)
  post(f'/admin/booking/{bids[1]}/edit',student_id=members[0],instructor_id=iid,duration='1',start_time=times[1],booking_state='booked')
  bid=max(bids);actor(iid);before=money()
  page=c.get(f'/instructor/lesson/{bid}/complete').get_data(as_text=True)
  for sid in members:
   assert f'name="worked_skill_{sid}"' in page
   assert f'id="level{sid}"' in page
  data={'actual_duration':'1.5'}
  for sid in members:
   data.update({f'status_{sid}':'completed',f'notes_{sid}':'QA retained <note>',f'level_{sid}':'1'})
  sid=members[0];data[f'worked_skill_{sid}']='l1_theory';data[f'progress_status_{sid}_l1_theory']='mastered'
  res=post(f'/instructor/group-complete/{bid}',**data)
  html=res.get_data(as_text=True)
  assert res.status_code==200
  assert money()==before
  assert 'QA retained &lt;note&gt;' in html
  assert 'value="1.5" selected' in html
  assert f'name="worked_skill_{sid}" value="l1_theory" checked' in html
  assert html.count('value="completed" selected')==size
  assert con.execute('SELECT COUNT(*) FROM instructor_hours').fetchone()[0]==0
  for sid in members:
   data[f'worked_skill_{sid}']='l1_theory';data[f'progress_status_{sid}_l1_theory']='mastered'
  res=post(f'/instructor/group-complete/{bid}',**data);assert res.status_code==302
  assert con.execute('SELECT actual_duration FROM bookings WHERE id=?',(bid,)).fetchone()[0]==1.5
  assert con.execute('SELECT SUM(hours) FROM instructor_hours WHERE booking_id=?',(bid,)).fetchone()[0]==1.5
  for sid in members:
   assert con.execute('SELECT credits FROM students WHERE user_id=?',(sid,)).fetchone()[0]==0.5
   assert con.execute('SELECT hours_remaining FROM student_packages WHERE student_id=?',(sid,)).fetchone()[0]==0.5
  after=money();post(f'/instructor/group-complete/{bid}',**data);assert money()==after
  assert con.execute('SELECT COUNT(*) FROM instructor_hours WHERE booking_id=?',(bid,)).fetchone()[0]==1

 for states in [('completed','makeup','no_show'),('makeup','no_show')]:
  members,bids,slots,times=setup(len(states));post(f'/admin/booking/{bids[1]}/edit',student_id=members[0],instructor_id=iid,duration='1',start_time=times[1],booking_state='booked');bid=max(bids);actor(iid)
  data={'actual_duration':'2'}
  for sid,state in zip(members,states):
   data[f'status_{sid}']=state
   if state=='completed':data[f'worked_skill_{sid}']='l1_theory'
  assert post(f'/instructor/group-complete/{bid}',**data).status_code==302
  for sid,state in zip(members,states):
   expected=2 if state=='makeup' else 0
   assert con.execute('SELECT credits FROM students WHERE user_id=?',(sid,)).fetchone()[0]==expected
  hours=con.execute('SELECT COALESCE(SUM(hours),0) FROM instructor_hours WHERE booking_id=?',(bid,)).fetchone()[0]
  assert hours==(2 if 'completed' in states else 0)
 print('PASS: 2P/3P curriculum; retained fields on atomic validation failure; actual-duration refunds; mixed attendance; instructor once; replay unchanged; email stubbed')
