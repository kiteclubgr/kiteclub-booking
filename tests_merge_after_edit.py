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
 for size in (1,2,3):
  for reverse in (False,True):
   members,bids,slots,times=setup(size,reverse);before=money()
   response=post(f'/admin/booking/{bids[1]}/edit',student_id=members[0],instructor_id=iid,duration='1',start_time=times[1],booking_state='booked')
   assert response.status_code==302
   assert money()==before,'Merge changed balance, amounts or package remaining hours'
   survivor=max(bids);old=min(bids)
   assert con.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]==1
   b=con.execute('SELECT * FROM bookings WHERE id=?',(survivor,)).fetchone();assert b['duration']==2 and b['slot_id']==slots[iid,'13:00'] and b['status']=='confirmed'
   assert {r[0] for r in con.execute('SELECT slot_id FROM booking_slots WHERE booking_id=?',(survivor,))}=={slots[iid,'13:00'],slots[iid,'14:00']}
   assert all(r[0]==2 for r in con.execute('SELECT credit_charged FROM booking_participants WHERE booking_id=?',(survivor,)))
   archive=con.execute('SELECT * FROM booking_merges WHERE source_booking_id=?',(old,)).fetchone();assert archive['surviving_booking_id']==survivor
   assert json.loads(archive['snapshot_json'])['booking']['duration']==1
   assert c.get(f'/admin/bookings/{old}/history').headers['Location'].endswith(f'/{survivor}/history')
   assert len(m.get_booking_audit(con,survivor))==4
   assert c.get(f'/admin/bookings/{survivor}/history').status_code==200
   # Replayed pre-merge edit cannot shrink the combined lesson back to one hour.
   post(f'/admin/booking/{bids[1]}/edit',student_id=members[0],instructor_id=iid,duration=1,original_duration=1,start_time=times[1],booking_state='booked')
   assert money()==before
   assert con.execute('SELECT duration FROM bookings WHERE id=?',(survivor,)).fetchone()[0]==2
   # Replayed old ID cannot refund or modify the retained lesson.
   post(f'/admin/booking/{old}/cancel');assert money()==before
   # Combined cancellation restores precisely 2 hours per participant/package.
   post(f'/admin/booking/{survivor}/cancel')
   assert all(con.execute('SELECT credits FROM students WHERE user_id=?',(s,)).fetchone()[0]==2 for s in members)
   assert all(r[0]==2 for r in con.execute('SELECT hours_remaining FROM student_packages'))
   after=money();post(f'/admin/booking/{survivor}/cancel');assert money()==after
   assert all(con.execute('SELECT status FROM slots WHERE id=?',(slots[iid,t],)).fetchone()[0]=='closed' for t in ('13:00','14:00'))
 # Actual private duration after merge: 2h reservation -> 1.5h worked -> +0.5h once.
 members,bids,slots,times=setup();post(f'/admin/booking/{bids[1]}/edit',student_id=members[0],instructor_id=iid,duration=1,start_time='14:00',booking_state='booked')
 survivor=max(bids);actor(iid)
 assert post(f'/instructor/complete/{survivor}',actual_duration='1.5',instructor_notes='QA',worked_skill='l1_theory').status_code==302
 assert con.execute('SELECT credits FROM students WHERE user_id=?',(members[0],)).fetchone()[0]==.5
 assert con.execute('SELECT hours_remaining FROM student_packages').fetchone()[0]==.5
 assert con.execute('SELECT actual_duration,status FROM bookings WHERE id=?',(survivor,)).fetchone()[:]==(1.5,'completed')
 assert con.execute('SELECT SUM(hours) FROM instructor_hours WHERE booking_id=?',(survivor,)).fetchone()[0]==1.5
 after=money();post(f'/instructor/complete/{survivor}',actual_duration='1.5',worked_skill='l1_theory');assert money()==after
 # New booking IDs cannot reuse archived IDs.
 newest=con.execute('INSERT INTO bookings(student_id) VALUES(?)',(members[0],)).lastrowid;assert newest>survivor;con.rollback()
 # Invalid candidate states are rejected without mutation.
 from booking_merge import merge_after_admin_edit
 for state in ('pending_payment','completed','cancelled_staff'):
  members,bids,slots,times=setup();con.execute("UPDATE slots SET instructor_id=? WHERE id=?",(iid,slots[other_iid,'14:00']));con.execute('UPDATE bookings SET status=? WHERE id=?',(state,bids[0]));con.commit();before=money()
  assert merge_after_admin_edit(con,bids[1],admin,m._booking_kind,m.log_booking_audit) is None;assert money()==before
 # Financial debt/receipt and already shared hour block automatic merging.
 for problem in ('debt','shared','different_members','different_spot','participant_credit'):
  members,bids,slots,times=setup();con.execute('UPDATE bookings SET slot_id=? WHERE id=?',(slots[iid,'14:00'],bids[1]));con.execute('UPDATE booking_slots SET slot_id=? WHERE booking_id=?',(slots[iid,'14:00'],bids[1]))
  if problem=='debt':con.execute('INSERT INTO lesson_debts(booking_id,student_id,original_price,price,created_at) VALUES(?,?,60,60,?)',(bids[0],members[0],day))
  if problem=='shared':
   extra=con.execute("INSERT INTO bookings(slot_id,student_id,status) VALUES(?,?,'confirmed')",(slots[iid,'14:00'],students[-1])).lastrowid;con.execute('INSERT INTO booking_slots VALUES(?,?)',(extra,slots[iid,'14:00']))
  if problem=='different_members':con.execute('UPDATE booking_participants SET student_id=? WHERE booking_id=?',(students[-1],bids[0]))
  if problem=='different_spot':con.execute('UPDATE slots SET spot_id=999 WHERE id=?',(slots[iid,'13:00'],))
  if problem=='participant_credit':con.execute('UPDATE booking_participants SET credit_charged=.5 WHERE booking_id=?',(bids[0],))
  con.commit();before=money();assert merge_after_admin_edit(con,bids[1],admin,m._booking_kind,m.log_booking_audit) is None,problem;assert money()==before
 # An error archiving the source rolls back the edit and all merge operations.
 members,bids,slots,times=setup();before=money()
 before_bookings=[tuple(r) for r in con.execute('SELECT * FROM bookings ORDER BY id')]
 before_links=[tuple(r) for r in con.execute('SELECT * FROM booking_slots ORDER BY booking_id,slot_id')]
 con.execute("CREATE TRIGGER reject_archive BEFORE INSERT ON booking_merges BEGIN SELECT RAISE(ABORT,'test archive failure'); END");con.commit()
 try:
  post(f'/admin/booking/{bids[1]}/edit',student_id=members[0],instructor_id=iid,duration=1,start_time='14:00',booking_state='booked')
  raise AssertionError('Expected archive failure')
 except Exception as exc:assert 'test archive failure' in str(exc),str(exc)
 assert money()==before
 assert [tuple(r) for r in con.execute('SELECT * FROM bookings ORDER BY id')]==before_bookings
 assert [tuple(r) for r in con.execute('SELECT * FROM booking_slots ORDER BY booking_id,slot_id')]==before_links
 con.execute('DROP TRIGGER reject_archive');con.commit()
 # Both edit entry points render original-duration state for stale-form checks.
 for path in ('/admin/bookings','/admin?date=2026-10-17'):
  r=c.get(path);assert r.status_code==200
  assert 'name="original_duration"' in r.get_data(as_text=True)
 assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok';con.close()
print('PASS: real Admin edit merges 1P/2P/3P in both time directions; no charge/refund; archived history; cancellation/refund/replay; actual 1.5h completion; unsafe candidates blocked; IDs not reused')
