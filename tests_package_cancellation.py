"""Offline HTTP and accounting regression tests, in a disposable application copy."""
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

source = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder) / 'app'
    shutil.copytree(source, root, ignore=shutil.ignore_patterns('.git', '_local_data', '*.db', '*.db-*', '__pycache__', 'uploads', '.local_secret_key'))
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location('launcher', root/'run_local.py')
    launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
    m = launcher.load_local_app(); m.app.config['TESTING'] = True
    c = m.app.test_client(); con = m.db()
    admin = con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    sid = con.execute('SELECT user_id FROM students ORDER BY user_id').fetchone()[0]
    with c.session_transaction() as s:
        s['uid'] = admin; s['_csrf_token'] = 'test-cancel-token'
    def post(pid, **kw):
        return c.post(f'/admin/package-purchases/{pid}/cancel', data={'_csrf_token':'test-cancel-token', **kw})
    def purchase(hours=2, price=110, active=1, status='unpaid', kind='lesson'):
        pid = con.execute('''INSERT INTO student_packages(student_id,package_name,hours_total,hours_remaining,price,payment_status,purchased_at,package_type,credits_activated,paid_amount)
            VALUES(?,?,?,?,?,?,?,?,?,?)''', (sid,'QA package',hours,hours if active else 0,price,status,'2026-10-16T09:00:00',kind,active,0)).lastrowid
        if active:
            con.execute('UPDATE students SET credits=credits+? WHERE user_id=?',(hours,sid))
            con.execute("INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,'package_activation',?,'2026-10-16T09:00:00')",(sid,hours,f'purchase #{pid}'))
        con.commit(); return pid
    def credits(): return con.execute('SELECT credits FROM students WHERE user_id=?',(sid,)).fetchone()[0]
    def snapshot():
        return {t:[tuple(r) for r in con.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in ('students','student_packages','credit_ledger','package_usage','bookings','student_payments','package_cancellations')}
    def confirm(pid, **fields):
        r = post(pid, action='preview', reason='Δοκιμή λανθασμένης αγοράς', **fields)
        match = re.search('name="preview_token" value="([a-f0-9]+)"',r.get_data(as_text=True))
        assert match, r.get_data(as_text=True)[-7000:]
        return post(pid, action='confirm',reason='Δοκιμή λανθασμένης αγοράς',preview_token=match[1],**fields)
    # GET is read-only, CSRF and role protection apply.
    pid = purchase(); before = snapshot()
    assert c.get(f'/admin/package-purchases/{pid}/cancel').status_code == 200
    assert snapshot() == before
    assert c.post(f'/admin/package-purchases/{pid}/cancel',data={'action':'confirm'}).status_code == 400
    outsider = m.app.test_client()
    assert outsider.get(f'/admin/package-purchases/{pid}/cancel').status_code == 403
    with outsider.session_transaction() as s: s['uid']=sid; s['_csrf_token']='x'
    assert outsider.post(f'/admin/package-purchases/{pid}/cancel',data={'_csrf_token':'x'}).status_code == 403
    # Standard unused cancellation: debt and credits removed, price retained, no cash.
    assert confirm(pid, mode='normal').status_code == 302
    assert credits() == 0
    assert con.execute('SELECT price,payment_status,hours_remaining FROM student_packages WHERE id=?',(pid,)).fetchone()[:] == (110,'cancelled',0)
    assert con.execute('SELECT COUNT(*) FROM student_payments').fetchone()[0] == 0
    before=snapshot(); post(pid,action='confirm',reason='repeat',mode='normal'); assert snapshot()==before
    for endpoint, data in ((f'/admin/package-purchases/{pid}/mark-paid',{}),(f'/admin/package-purchases/{pid}/payments/add',{'payment_request_id':'cancelled-request-123456789','amount':'1'})):
        assert c.post(endpoint,data={'_csrf_token':'test-cancel-token',**data}).status_code==409
    assert snapshot()==before
    # Inactive, unpaid package can be voided without changing credits.
    inactive=purchase(active=0); assert confirm(inactive,mode='normal').status_code==302; assert credits()==0
    # Stale preview, missing reason, tampering and paid purchases cannot mutate data.
    stale=purchase(); fields=dict(action='preview',mode='normal',reason='Δοκιμή λανθασμένης αγοράς')
    r=post(stale,**fields); token=re.search('name="preview_token" value="([a-f0-9]+)"',r.get_data(as_text=True))[1]
    con.execute('UPDATE students SET credits=credits+1 WHERE user_id=?',(sid,));con.commit(); before=snapshot()
    post(stale,action='confirm',mode='normal',reason=fields['reason'],preview_token=token);assert snapshot()==before
    post(stale,action='confirm',mode='normal',reason=fields['reason'],preview_token='bad');assert snapshot()==before
    post(stale,action='preview',mode='normal',reason='');assert snapshot()==before
    paid=purchase(status='paid');before=snapshot();post(paid,action='preview',mode='normal',reason='wrong paid purchase');assert snapshot()==before
    # Restore fixture balance; exact reported #17 scenario: wrong grant +2, manual -2,
    # correct grant +2, booking -2 consumed from wrong package by FIFO.
    old=purchase(); new=purchase(price=80,kind='group_2p')
    mid=con.execute("INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,-2,'manual_adjustment','Wrong initial purchase','2026-10-16T09:10:00')",(sid,)).lastrowid
    bid=con.execute("INSERT INTO bookings(student_id,duration,status,payment_status) VALUES(?,2,'confirmed','credit')",(sid,)).lastrowid
    con.execute('UPDATE students SET credits=credits-4 WHERE user_id=?',(sid,))
    con.execute('UPDATE student_packages SET hours_remaining=0 WHERE id=?',(old,))
    con.execute("INSERT INTO package_usage(student_package_id,student_id,booking_id,amount,kind,created_at) VALUES(?,?,?,-2,'booking_use','2026-10-16T09:20:00')",(old,sid,bid))
    con.execute("INSERT INTO credit_ledger(student_id,booking_id,amount,kind,note,created_at) VALUES(?,?,-2,'booking','QA','2026-10-16T09:20:00')",(sid,bid));con.commit()
    # Used normal cancellation is blocked. Manual mode needs explicit evidence and acknowledgement.
    before=snapshot();post(old,action='preview',mode='normal',reason='wrong initial purchase');assert snapshot()==before
    options=dict(mode='manual',manual_ledger_id=str(mid),replacement_purchase_id=str(new),manual_ack='yes')
    bad={**options,'manual_ack':'no'};post(old,action='preview',reason='wrong initial purchase',**bad);assert snapshot()==before
    bad={**options,'replacement_purchase_id':str(inactive)};post(old,action='preview',reason='wrong initial purchase',**bad);assert snapshot()==before
    debt_before=con.execute("SELECT SUM(price-paid_amount) FROM student_packages WHERE payment_status IN ('unpaid','partial','pending')").fetchone()[0]
    ledger_before=con.execute('SELECT SUM(amount) FROM credit_ledger WHERE student_id=?',(sid,)).fetchone()[0]
    old_balance=credits(); booking_before=tuple(con.execute('SELECT * FROM bookings WHERE id=?',(bid,)).fetchone())
    assert confirm(old,**options).status_code==302
    assert credits()==old_balance
    assert con.execute("SELECT SUM(price-paid_amount) FROM student_packages WHERE payment_status IN ('unpaid','partial','pending')").fetchone()[0]==debt_before-110
    assert con.execute('SELECT SUM(amount) FROM credit_ledger WHERE student_id=?',(sid,)).fetchone()[0]==ledger_before
    assert tuple(con.execute('SELECT * FROM bookings WHERE id=?',(bid,)).fetchone())==booking_before
    assert con.execute('SELECT hours_remaining FROM student_packages WHERE id=?',(new,)).fetchone()[0]==0
    assert con.execute('SELECT SUM(amount) FROM package_usage WHERE student_package_id=?',(old,)).fetchone()[0]==0
    assert con.execute('SELECT SUM(amount) FROM package_usage WHERE student_package_id=?',(new,)).fetchone()[0]==-2
    assert con.execute('SELECT COUNT(*) FROM student_payments').fetchone()[0]==0
    assert con.execute('SELECT manual_ledger_id FROM package_cancellations WHERE purchase_id=?',(old,)).fetchone()[0]==mid
    # Cancelling the booking later refunds its replacement package exactly once.
    m._refund_package_hours(con,sid,bid);con.commit()
    assert con.execute('SELECT hours_remaining FROM student_packages WHERE id=?',(new,)).fetchone()[0]==2
    assert con.execute('SELECT hours_remaining FROM student_packages WHERE id=?',(old,)).fetchone()[0]==0
    assert m._refund_package_hours(con,sid,bid)==0;con.commit()
    # Explicit prior manual removal without booking usage leaves balance unchanged.
    unused=purchase(); mid2=con.execute("INSERT INTO credit_ledger(student_id,amount,kind,created_at) VALUES(?,-2,'manual_adjustment','2026-10-16T09:10:00')",(sid,)).lastrowid
    con.execute('UPDATE students SET credits=credits-2 WHERE user_id=?',(sid,));con.commit()
    balance=credits(); assert confirm(unused,mode='manual',manual_ledger_id=str(mid2),manual_ack='yes').status_code==302; assert credits()==balance
    # A failed audit write rolls the entire cancellation back, including the debit.
    rollback_pid=purchase(); before=snapshot()
    con.execute("CREATE TRIGGER reject_cancel BEFORE INSERT ON package_cancellations BEGIN SELECT RAISE(ABORT, 'test audit failure'); END");con.commit()
    try:
        confirm(rollback_pid,mode='normal')
        raise AssertionError('Expected forced audit failure')
    except Exception as exc:
        assert 'test audit failure' in str(exc), str(exc)
    assert snapshot()==before
    con.execute('DROP TRIGGER reject_cancel');con.commit()
    # Any receipt blocks cancellation, even if an inconsistent status says unpaid.
    receipt_pid=purchase(); con.execute("INSERT INTO student_payments(student_id,purchase_id,amount,payment_date,created_at) VALUES(?,?,1,'2026-10-16','2026-10-16T10:00:00')",(sid,receipt_pid));con.commit();before=snapshot()
    post(receipt_pid,action='preview',mode='normal',reason='Wrong package with receipt');assert snapshot()==before
    # Views agree on cancelled status and remain renderable; all templates compile.
    for path in (f'/admin/students/{sid}','/admin','/admin/packages','/admin/debts','/admin/finance','/admin/reports',f'/admin/package-purchases/{old}/cancel'):
        response=c.get(path);assert response.status_code==200,(path,response.status_code)
    assert 'Ακυρωμένο' in c.get(f'/admin/students/{sid}').get_data(as_text=True)
    for template in m.app.jinja_env.list_templates(): m.app.jinja_env.get_template(template)
    assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    audit=json.loads(con.execute('SELECT details_json FROM package_cancellations WHERE purchase_id=?',(old,)).fetchone()[0]); assert audit['replacement']['id']==new
    con.close()
print('PASS: cancellation HTTP security, accounting, manual correction, transfer/refund, replay, stale preview, cash protection and templates')
