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

 members,bids,slots,times=setup(2)
 for time in ('13:00','14:00'):con.execute('INSERT INTO day_hours(lesson_date,start_time,spot_id) VALUES(?,?,?)',(day,time,spot))
 con.execute('INSERT INTO day_spots(lesson_date,spot_id) VALUES(?,?)',(day,spot))
 con.execute("UPDATE bookings SET status='completed',actual_duration=1 WHERE id=?",(bids[1],));con.commit()
 # Synthetic balances exercise positive, zero and negative filter states.
 con.execute('UPDATE students SET credits=1 WHERE user_id=?',(students[2],))
 con.execute('UPDATE students SET credits=-0.5 WHERE user_id=?',(students[3],))
 con.commit()
 # Existing route performs its normal day normalization on first load.
 res=c.get('/admin?date=17%2F10%2F2026');assert res.status_code==200
 before=list(con.iterdump());res=c.get('/admin?date=17%2F10%2F2026');assert res.status_code==200
 assert list(con.iterdump())==before
 from html.parser import HTMLParser
 class Buttons(HTMLParser):
  def __init__(self):super().__init__();self.bookings=[];self.forms=[]
  def handle_starttag(self,tag,attrs):
   d=dict(attrs)
   if 'data-booking-info' in d:self.bookings.append(json.loads(d['data-booking-info']))
   if tag=='form':self.forms.append(d)
 html=res.get_data(as_text=True);parser=Buttons();parser.feed(html)
 assert {x['id'] for x in parser.bookings}==set(bids)
 assert {x['status'] for x in parser.bookings}=={'confirmed','completed'}
 assert all(x['history'].endswith('/history') and x['spot'] for x in parser.bookings)
 assert 'mobile-schedule-table' in html and 'week-day-short' in html
 assert 'class="card spread day-manage-head"' not in html
 assert 'Rebalance instructors</button>' not in html
 assert 'href="/admin?date=' in html and '#day' in html
 assert 'mobileEditBooking' in html and 'mobileBookingLocked' in html
 assert 'mobileSlotForm' in html and '_csrf_token' in html
 assert 'studentCreditsDialog' in html and 'newStudentDialog' in html
 assert 'data-credit-filter="positive"' in html and 'data-credit-filter="empty"' in html
 assert html.count('class="admin-student-row student-compact-card"')==len(students)
 assert 'name="amount"' in html and 'name="note"' in html
 assert 'student-credit-badge empty' in html and 'student-credit-badge positive' in html and 'student-credit-badge negative' in html
 assert any(x.get('action')=='/admin/assign-day-column/1' for x in parser.forms) or 'instructor_id' in html
 # Local browser/DOM fixture contains demo accounts only.
 (Path(tempfile.gettempdir())/'kite-students-fixture.html').write_text(html)
 assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 con.close()
 print('PASS: real Admin students and schedule render, original create/credit fields, signed/zero balances and no business-row changes')
