"""Merge two already charged adjacent lessons without financial movements."""
import json
from datetime import datetime, timedelta


def ensure_merge_schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS booking_merges (
        source_booking_id INTEGER PRIMARY KEY,
        surviving_booking_id INTEGER NOT NULL,
        actor_id INTEGER NOT NULL, merged_at TEXT NOT NULL,
        snapshot_json TEXT NOT NULL)''')


def merge_after_admin_edit(con, booking_id, actor, booking_kind, log_audit):
    """Inside caller's IMMEDIATE transaction; no commit, credit charge or refund.

    Retain the larger ID so deleting the source cannot cause SQLite's implicit
    INTEGER PRIMARY KEY allocator to reuse the archived source ID.
    The full source, participant and slot records are archived; original audit
    rows keep their IDs and are included in the survivor's history.
    """
    rows=con.execute('''SELECT b.*,s.lesson_date,s.start_time,s.instructor_id,s.spot_id
        FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.id=?''',(booking_id,)).fetchall()
    if not rows:return None
    edited=rows[0]
    if edited['status']!='confirmed' or float(edited['duration'] or 0)!=1 or edited['payment_status']!='credit':return None
    current=datetime.strptime(edited['start_time'],'%H:%M')
    times=[(current-timedelta(hours=1)).strftime('%H:%M'),(current+timedelta(hours=1)).strftime('%H:%M')]
    candidates=con.execute('''SELECT b.*,s.lesson_date,s.start_time,s.instructor_id,s.spot_id
        FROM bookings b JOIN slots s ON s.id=b.slot_id
        WHERE b.id<>? AND b.status='confirmed' AND b.payment_status='credit' AND b.duration=1
          AND s.lesson_date=? AND s.instructor_id=? AND s.spot_id=? AND s.start_time IN (?,?)
        ORDER BY s.start_time,b.id''',(booking_id,edited['lesson_date'],edited['instructor_id'],edited['spot_id'],*times)).fetchall()
    for other in candidates:
        pair=[edited,other]
        # Explicit one-hour distance also rejects a spurious 23:00/00:00 wrap.
        if abs((datetime.strptime(other['start_time'],'%H:%M')-current).total_seconds())!=3600:continue
        kind=booking_kind(con,booking_id)
        if kind not in ('private','2p','3p') or booking_kind(con,other['id'])!=kind:continue
        participant_rows={r['id']:con.execute('SELECT * FROM booking_participants WHERE booking_id=? ORDER BY student_id',(r['id'],)).fetchall() for r in pair}
        expected={'private':1,'2p':2,'3p':3}[kind]
        if any(len(v)!=expected for v in participant_rows.values()):continue
        if {r['student_id'] for r in participant_rows[edited['id']]}!={r['student_id'] for r in participant_rows[other['id']]}:continue
        if any(r['payment_status']!='credit' or abs(float(r['credit_charged'] or 0)-1)>1e-8 or float(r['amount'] or 0)!=0 or r['attendance_status'] is not None or r['participant_notes'] or r['participant_next_skill'] for v in participant_rows.values() for r in v):continue
        if any(float(r['amount'] or 0)!=0 or r['actual_duration'] is not None or r['completed_at'] or r['instructor_notes'] or r['next_skill'] for r in pair):continue
        ids=sorted([edited['id'],other['id']]); source_id,survivor_id=ids
        if con.execute('SELECT 1 FROM lesson_debts WHERE booking_id IN (?,?) LIMIT 1',ids).fetchone():continue
        if con.execute('SELECT 1 FROM instructor_hours WHERE booking_id IN (?,?) LIMIT 1',ids).fetchone():continue
        links={r['id']:con.execute('SELECT slot_id FROM booking_slots WHERE booking_id=?',(r['id'],)).fetchall() for r in pair}
        if any(len(links[r['id']])!=1 or links[r['id']][0]['slot_id']!=r['slot_id'] for r in pair):continue
        slots=[r['slot_id'] for r in pair]
        overlaps=con.execute('''SELECT DISTINCT b.id FROM bookings b JOIN booking_slots bs ON bs.booking_id=b.id
            WHERE bs.slot_id IN (?,?) AND b.status IN ('confirmed','pending_payment','completed','no_show')''',slots).fetchall()
        if {r['id'] for r in overlaps}!=set(ids):continue
        # Every linked usage must belong to one of the actual participants.
        members={r['student_id'] for r in participant_rows[source_id]}
        usage=con.execute('SELECT student_id FROM package_usage WHERE booking_id IN (?,?)',ids).fetchall()
        if any(r['student_id'] not in members for r in usage):continue
        source=next(r for r in pair if r['id']==source_id)
        snapshot={'booking':dict(source),'participants':[dict(r) for r in participant_rows[source_id]],
                  'slot_links':[dict(r) for r in links[source_id]],
                  'credit_ledger':[dict(r) for r in con.execute('SELECT * FROM credit_ledger WHERE booking_id=?',(source_id,))],
                  'package_usage':[dict(r) for r in con.execute('SELECT * FROM package_usage WHERE booking_id=?',(source_id,))]}
        con.execute('INSERT INTO booking_merges VALUES(?,?,?,?,?)',(source_id,survivor_id,actor['id'],datetime.now().isoformat(),json.dumps(snapshot,ensure_ascii=False,sort_keys=True)))
        con.execute('UPDATE booking_merges SET surviving_booking_id=? WHERE surviving_booking_id=?',(survivor_id,source_id))
        # Preserve exact ledger amounts and package balances. Only ownership of
        # existing usage/charges changes; future refunds use the combined lesson.
        con.execute('UPDATE package_usage SET booking_id=? WHERE booking_id=?',(survivor_id,source_id))
        con.execute('UPDATE credit_ledger SET booking_id=? WHERE booking_id=?',(survivor_id,source_id))
        con.execute('UPDATE booking_participants SET credit_charged=2 WHERE booking_id=?',(survivor_id,))
        first=min(pair,key=lambda r:r['start_time'])
        con.execute('UPDATE bookings SET slot_id=?,duration=2 WHERE id=?',(first['slot_id'],survivor_id))
        con.execute('DELETE FROM booking_slots WHERE booking_id=?',(source_id,))
        con.execute('INSERT OR IGNORE INTO booking_slots(booking_id,slot_id) VALUES(?,?)',(survivor_id,source['slot_id']))
        con.execute('DELETE FROM booking_participants WHERE booking_id=?',(source_id,))
        con.execute('DELETE FROM bookings WHERE id=?',(source_id,))
        log_audit(con,survivor_id,'merged','Δύο ήδη χρεωμένες μονόωρες κρατήσεις ενώθηκαν μετά από επεξεργασία. Δεν άλλαξαν credits ή πληρωμές.',actor['id'],actor['role'],f'source_booking={source_id}; surviving_booking={survivor_id}; start={first["start_time"]}; duration=2; members={len(members)}')
        return survivor_id
    return None
