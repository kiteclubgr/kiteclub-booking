"""Regression for /admin/reports' hour-calculation block (no Flask dependency).
Run: python tests_reports_hours.py
"""
import sqlite3
from pathlib import Path

p=Path(__file__).with_name('app.py')
source=p.read_text(encoding='utf8')
start=source.index('    # Count occupied instructor time',source.index('def admin_reports():'))
end=source.index('    sales=con.execute',start)
block=source[start:end]

con=sqlite3.connect(':memory:'); con.row_factory=sqlite3.Row
con.executescript('''
CREATE TABLE users (id INTEGER PRIMARY KEY,name TEXT,surname TEXT,profile_photo TEXT,active INTEGER DEFAULT 1);
CREATE TABLE instructors (user_id INTEGER PRIMARY KEY,hourly_rate REAL);
CREATE TABLE students (user_id INTEGER PRIMARY KEY,student_code TEXT,lesson_type TEXT);
CREATE TABLE slots (id INTEGER PRIMARY KEY,lesson_date TEXT,start_time TEXT,duration REAL,instructor_id INTEGER);
CREATE TABLE bookings (id INTEGER PRIMARY KEY,slot_id INTEGER,student_id INTEGER,duration REAL,status TEXT);
CREATE TABLE booking_slots (booking_id INTEGER,slot_id INTEGER);
CREATE TABLE booking_participants (booking_id INTEGER,student_id INTEGER,attendance_status TEXT);
INSERT INTO users(id,name) VALUES (1,'Teacher'),(2,'Alex'),(3,'Maria');
INSERT INTO instructors(user_id,hourly_rate) VALUES(1,15);
INSERT INTO students(user_id,student_code,lesson_type) VALUES(2,'STU-2','private'),(3,'STU-3','private');
INSERT INTO slots VALUES(1,'2026-10-13','10:00',1,1),(2,'2026-10-13','11:00',1,1),(3,'2026-10-13','13:00',1,1),(4,'2026-10-14','09:00',1,1);
-- Two students share a completed 2-hour session.
INSERT INTO bookings VALUES(10,1,2,2,'completed'),(11,1,3,2,'completed');
INSERT INTO booking_participants VALUES(10,2,'completed'),(11,3,'completed');
INSERT INTO booking_slots VALUES(10,1),(10,2),(11,1),(11,2);
-- A cancelled booking must not add hours.
INSERT INTO bookings VALUES(12,3,2,1,'cancelled_student');
INSERT INTO booking_participants VALUES(12,2,NULL);
INSERT INTO booking_slots VALUES(12,3);
-- A future 1-hour active booking must add Booked but not Completed.
INSERT INTO bookings VALUES(13,4,2,1,'confirmed');
INSERT INTO booking_participants VALUES(13,2,NULL);
INSERT INTO booking_slots VALUES(13,4);
''')
ctx={'con':con,'date_from':'2026-10-12','date_to':'2026-10-18'}
exec('def calculate():\n'+block+'\n    return locals()\n',ctx)
r=ctx['calculate']()
assert r['booked_hours']==3, r['booked_hours']
assert r['completed_hours']==2, r['completed_hours']
assert r['shared_hours']==2, r['shared_hours']
assert r['lesson_mix']['shared']==2, r['lesson_mix']
assert len(r['instructors'])==1
assert r['instructors'][0]['booked_hours']==3
assert r['instructors'][0]['completed_hours']==2
assert r['instructors'][0]['estimated_pay']==30
assert r['estimated_pay']==30
students={x['name']:x for x in r['top_students']}
assert students['Alex']['lesson_hours']==3
assert students['Alex']['completed_hours']==2
assert students['Maria']['lesson_hours']==2
assert students['Maria']['completed_hours']==2
print('PASS: future booked, completed duration, 2 shared students, cancelled exclusion, pay, top student hours')
