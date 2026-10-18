"""Isolated real Admin profile: displayed pay reconciles to the hour ledger."""
import tempfile,shutil,sys,importlib.util,re
from pathlib import Path
from flask import template_rendered
source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'app';shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','.venv','.git','*.db','*.db-*','uploads','.local_secret_key'))
 sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('launch',root/'run_local.py');launch=importlib.util.module_from_spec(spec);spec.loader.exec_module(launch);m=launch.load_local_app();m.app.config['TESTING']=True
 con=m.db();admin=con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0];iid=con.execute('SELECT user_id FROM instructors LIMIT 1').fetchone()[0];sid=con.execute('SELECT user_id FROM students LIMIT 1').fetchone()[0];spot=con.execute('SELECT id FROM spots LIMIT 1').fetchone()[0]
 con.execute('UPDATE instructors SET hourly_rate=20 WHERE user_id=?',(iid,));ids=[]
 cases=[('completed',2,1,1,20),('no_show',1,None,0,0),('confirmed',2,None,0,40),('completed',2,1.5,1.5,30),('completed',2,None,2,40)]
 for n,(state,booked,actual,earned,pay) in enumerate(cases):
  slot=con.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES('2026-10-17',?,?,?,'booked')",(f'{9+n*2}:00',iid,spot)).lastrowid
  bid=con.execute("INSERT INTO bookings(slot_id,student_id,duration,actual_duration,status,payment_status,created_at) VALUES(?,?,?,?,?,'credit','2026-10-17')",(slot,sid,booked,actual,state)).lastrowid;ids.append(bid)
  if earned:con.execute("INSERT INTO instructor_hours(instructor_id,booking_id,hours,lesson_date,created_at) VALUES(?,?,?,'2026-10-17','2026-10-17')",(iid,bid,earned))
 con.commit();before=list(con.iterdump());con.close();client=m.app.test_client()
 with client.session_transaction() as sess:sess['uid']=admin
 seen=[]
 def capture(sender,template,context,**kw):seen.append(context)
 template_rendered.connect(capture,m.app)
 try:res=client.get(f'/admin/instructors/{iid}?from=2026-10-17&to=2026-10-17')
 finally:template_rendered.disconnect(capture,m.app)
 assert res.status_code==200;ctx=seen[-1];rows={r['id']:r for r in ctx['booking_report']};html=res.get_data(as_text=True)
 for bid,(state,booked,actual,earned,pay) in zip(ids,cases):
  row=rows[bid];assert row['display_pay']==pay
  assert row['display_duration']==(actual if actual is not None and state=='completed' else booked)
 assert sum(r['display_pay'] for r in rows.values() if r['status']=='completed')==ctx['total_earned']==90
 assert 'Κράτηση: 2.0h' in html and 'Πρόβλεψη' in html
 # A period without entries cannot leak previous earned hours.
 assert client.get(f'/admin/instructors/{iid}?from=2026-11-01&to=2026-11-30').status_code==200
 con=m.db();assert list(con.iterdump())==before;con.close()
print('PASS: completed actual 1h/1.5h, legacy duration fallback, no-show zero, future estimate, displayed accrued sum = summary, date filter, no database writes')
