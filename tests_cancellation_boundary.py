"""Cancellation cutoff regression on disposable local data, never the live database."""
import importlib.util
import shutil
import sys
import tempfile
from datetime import datetime as RealDateTime, timedelta
from pathlib import Path

source = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder) / 'app'
    shutil.copytree(source, root, ignore=shutil.ignore_patterns(
        '_local_data', '__pycache__', '*.db', '*.db-*', 'uploads', '.local_secret_key', '.git'))
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location('boundary_launcher', root / 'run_local.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    m = launcher.load_local_app()
    m.app.config['TESTING'] = True
    m.send_email = lambda *args, **kwargs: None
    client = m.app.test_client()
    con = m.db()
    students = [r[0] for r in con.execute('SELECT user_id FROM students ORDER BY user_id LIMIT 3')]
    instructor = con.execute('SELECT user_id FROM instructors ORDER BY user_id LIMIT 1').fetchone()[0]
    spot = con.execute('SELECT id FROM spots LIMIT 1').fetchone()[0]
    start = RealDateTime(2030, 1, 15, 13)

    class FrozenDateTime(RealDateTime):
        current = start

        @classmethod
        def now(cls, tz=None):
            assert tz is None
            return cls.current

    m.datetime = FrozenDateTime
    for size in (1, 2, 3):
        for remaining, allowed in ((timedelta(hours=6, minutes=1), True),
                                   (timedelta(hours=6), True),
                                   (timedelta(hours=5, minutes=59), False)):
            for table in ('booking_merges', 'booking_audit', 'booking_slots', 'booking_participants',
                          'package_usage', 'credit_ledger', 'lesson_payments', 'lesson_debts',
                          'instructor_hours', 'bookings', 'slots', 'day_columns', 'day_hours',
                          'day_spots', 'student_packages', 'student_groups'):
                con.execute(f'DELETE FROM {table}')
            con.execute("UPDATE students SET credits=10, lesson_type='private', group_id=NULL")
            members = students[:size]
            slot = con.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES(?,?,?,?, 'open')",
                               ('2030-01-15', '13:00', instructor, spot)).lastrowid
            bid = con.execute("INSERT INTO bookings(slot_id,student_id,duration,status,payment_status,group_lesson_type,created_at) VALUES(?,?,1,'confirmed','credit',?,?)",
                              (slot, members[0], {1:'private',2:'2p',3:'3p'}[size], start.isoformat())).lastrowid
            m._charge_booking_participants(con, bid, members, 1)
            con.execute('INSERT INTO booking_slots VALUES(?,?)', (bid, slot))
            con.execute("UPDATE slots SET status='booked' WHERE id=?", (slot,))
            con.commit()
            before = list(con.iterdump())
            FrozenDateTime.current = start - remaining
            with client.session_transaction() as session:
                session['uid'] = members[-1]
                session['_csrf_token'] = 'boundary-qa'
            result = client.post(f'/booking/{bid}/cancel', data={'_csrf_token':'boundary-qa'})
            assert result.status_code == 302
            if not allowed:
                assert list(con.iterdump()) == before, 'late cancellation mutated state'
            else:
                assert con.execute('SELECT status FROM bookings WHERE id=?', (bid,)).fetchone()[0] == 'cancelled_student'
                assert con.execute('SELECT status FROM slots WHERE id=?', (slot,)).fetchone()[0] == 'open'
                for sid in students:
                    assert con.execute('SELECT credits FROM students WHERE user_id=?', (sid,)).fetchone()[0] == 10
                after = list(con.iterdump())
                client.post(f'/booking/{bid}/cancel', data={'_csrf_token':'boundary-qa'})
                assert list(con.iterdump()) == after, 'repeat cancellation refunded twice'
            print(f'PASS isolated HTTP: {size}P, {remaining}, allowed={allowed}; ledger and slots verified')
