"""Regression checks for scheduled vs actual lesson duration in student views."""
import re
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment()


def render_duration(template_name, context, anchor):
    source = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
    line = next(line for line in source.splitlines() if anchor in line)
    expression = re.search(r"{{\s*([^}]*actual_duration[^}]*)\s*}}", line)
    assert expression, f"Missing actual-duration expression in {template_name}"
    return ENV.from_string("{{ " + expression.group(1) + " }}").render(**context)


class StudentActualDurationDisplayTests(unittest.TestCase):
    def test_completed_history_shows_actual_duration(self):
        b = SimpleNamespace(duration=2.0, actual_duration=1.5, status="completed")
        self.assertEqual(render_duration("student_profile.html", {"b": b}, "Ιστορικό ολοκληρωμένων"), "1.5")

    def test_completed_history_falls_back_if_actual_missing(self):
        b = SimpleNamespace(duration=2.0, actual_duration=None, status="completed")
        self.assertEqual(render_duration("student_profile.html", {"b": b}, "Ιστορικό ολοκληρωμένων"), "2")

    def test_booking_list_completed_shows_actual_but_upcoming_scheduled(self):
        b = SimpleNamespace(duration=2.0, actual_duration=1.5, status="completed")
        self.assertEqual(render_duration("student.html", {"b": b}, "b.spot"), "1.5")
        b.status = "confirmed"
        self.assertEqual(render_duration("student.html", {"b": b}, "b.spot"), "2")


class StudentDurationLifecycleTests(unittest.TestCase):
    def test_booking_completion_refund_and_full_student_pages(self):
        original_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / 'app'
                shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
                    '_local_data', '__pycache__', '*.db', '*.db-*', 'uploads',
                    '.local_secret_key', '.git'))
                spec = importlib.util.spec_from_file_location('duration_launcher', root / 'run_local.py')
                launcher = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(launcher)
                module = launcher.load_local_app()
                module.app.config['TESTING'] = True
                module.send_email = lambda *args, **kwargs: None
                client = module.app.test_client()
                con = module.db()
                sid = con.execute('SELECT user_id FROM students ORDER BY user_id LIMIT 1').fetchone()[0]
                iid = con.execute('SELECT user_id FROM instructors ORDER BY user_id LIMIT 1').fetchone()[0]
                spot = con.execute('SELECT id FROM spots LIMIT 1').fetchone()[0]
                for table in ('booking_merges', 'booking_audit', 'booking_slots',
                              'booking_participants', 'package_usage', 'credit_ledger',
                              'lesson_payments', 'lesson_debts', 'instructor_hours',
                              'bookings', 'slots', 'day_columns', 'day_hours',
                              'day_spots', 'student_packages', 'student_groups'):
                    con.execute(f'DELETE FROM {table}')
                con.execute("UPDATE students SET credits=0,lesson_type='private',group_id=NULL")
                con.execute('UPDATE students SET credits=2 WHERE user_id=?', (sid,))
                con.execute("UPDATE spots SET name='QA Duration Spot' WHERE id=?", (spot,))
                con.execute("INSERT INTO student_packages(student_id,package_name,hours_total,hours_remaining,price,payment_status,purchased_at,package_type,credits_activated) VALUES(?,'QA duration',2,2,0,'paid','2030-01-01','lesson',1)", (sid,))
                slots = [con.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES('2030-01-15',?,?,?,'open')", (time, iid, spot)).lastrowid for time in ('10:00', '11:00')]
                con.commit()

                def actor(uid):
                    with client.session_transaction() as session:
                        session['uid'] = uid
                        session['_csrf_token'] = 'duration-lifecycle-qa'

                actor(sid)
                response = client.post(f'/book/{slots[0]}', data={'duration':'2', '_csrf_token':'duration-lifecycle-qa'})
                self.assertEqual(response.status_code, 302)
                bid = con.execute('SELECT id FROM bookings').fetchone()[0]
                self.assertEqual(con.execute('SELECT credits FROM students WHERE user_id=?', (sid,)).fetchone()[0], 0)
                scheduled = client.get('/student?date=15/01/2030')
                self.assertEqual(scheduled.status_code, 200)
                self.assertIn('QA Duration Spot · 2 ώρες', scheduled.get_data(as_text=True))

                actor(iid)
                response = client.post(f'/instructor/complete/{bid}', data={
                    '_csrf_token':'duration-lifecycle-qa', 'actual_duration':'1.5',
                    'worked_skill':'l1_theory', 'instructor_notes':'QA duration lifecycle'})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(con.execute('SELECT actual_duration,status FROM bookings WHERE id=?', (bid,)).fetchone()[:], (1.5, 'completed'))
                self.assertEqual(con.execute('SELECT credits FROM students WHERE user_id=?', (sid,)).fetchone()[0], .5)
                self.assertEqual(con.execute('SELECT hours_remaining FROM student_packages').fetchone()[0], .5)
                self.assertEqual(con.execute('SELECT SUM(hours) FROM instructor_hours WHERE booking_id=?', (bid,)).fetchone()[0], 1.5)

                actor(sid)
                for path in ('/student/profile?view=lessons', '/student/profile'):
                    page = client.get(path)
                    self.assertEqual(page.status_code, 200)
                    history = page.get_data(as_text=True).split('id="history"', 1)[1]
                    self.assertIn('<td>1.5h</td>', history)
                    self.assertNotIn('<td>2h</td>', history)
                profile = client.get('/student/profile').get_data(as_text=True)
                self.assertIn('Completed <b>1.5h</b>', profile)
                listing = client.get('/student?date=15/01/2030')
                self.assertEqual(listing.status_code, 200)
                self.assertIn('QA Duration Spot · 1.5 ώρες', listing.get_data(as_text=True))
                con.close()
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
