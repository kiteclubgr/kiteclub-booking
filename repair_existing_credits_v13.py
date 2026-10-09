'''One-time, explicit, idempotent repair for previously UNPAID lesson packages.

Run on a stopped app or consistent copy of its SQLite database. Default is DRY RUN.
Examples:
  python repair_existing_credits_v13.py --db /data/kiteclub.db --student-id 16
  python repair_existing_credits_v13.py --db /data/kiteclub.db --student-id 16 --purchase-ids 23,24 --apply

Never include the live database in git or patch archives.
'''
import argparse
import datetime
import shutil
import sqlite3
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--db',required=True)
p.add_argument('--student-id',type=int,required=True,help='Database user_id, NOT STU code')
p.add_argument('--purchase-ids',help='Comma-separated purchase IDs to repair (required for --apply)')
p.add_argument('--apply',action='store_true',help='Back up DB and apply only the listed purchases')
a=p.parse_args()
path=Path(a.db).expanduser().resolve()
if not path.is_file(): p.error('Database file not found')
ids=None
if a.purchase_ids:
    try: ids={int(v.strip()) for v in a.purchase_ids.split(',') if v.strip()}
    except ValueError: p.error('Invalid purchase IDs')
if a.apply and not ids: p.error('--apply requires explicit --purchase-ids')
con=sqlite3.connect(str(path),timeout=30); con.row_factory=sqlite3.Row
rows=con.execute('''SELECT id,student_id,package_name,hours_total,hours_remaining,paid_amount,
                   payment_status,credits_activated,package_type
                   FROM student_packages WHERE student_id=? ORDER BY id''',(a.student_id,)).fetchall()
if not rows:
    print('No purchases for this student; no changes'); con.close(); raise SystemExit(1)
student=con.execute('SELECT credits FROM students WHERE user_id=?',(a.student_id,)).fetchone()
if not student:
    print('Student record missing; no changes'); con.close(); raise SystemExit(1)
print(f'Student user_id={a.student_id}, CURRENT credits={student["credits"]}')
selected=[]
for r in rows:
    note=con.execute("SELECT COUNT(*) FROM credit_ledger WHERE student_id=? AND kind='package_activation' AND note LIKE ?",(a.student_id,f'%purchase #{r["id"]})%')).fetchone()[0]
    eligible=(r['package_type'] or 'lesson')=='lesson' and not int(r['credits_activated'] or 0) and note==0 and float(r['hours_total'] or 0)>0
    print(f"  purchase #{r['id']}: {r['package_name']}, {r['hours_total']}h, payment={r['payment_status']}, activated={r['credits_activated']}, activation_ledgers={note}, eligible={eligible}")
    if ids is not None and r['id'] in ids:
        if not eligible: p.error(f'Purchase #{r["id"]} is not safely eligible; check manually')
        selected.append(r)
if ids is not None and ids!={r['id'] for r in selected}: p.error('Some requested purchase IDs do not belong to student or are ineligible')
if not a.apply:
    print('DRY RUN ONLY. To apply choose exact purchase IDs and --apply.'); con.close(); raise SystemExit(0)
# SQLite online backup API provides consistent copy even if the source is in WAL mode.
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup=path.with_name(path.name+f'.pre-v13-{stamp}.bak')
backup_con=sqlite3.connect(str(backup)); con.backup(backup_con); backup_con.close()
print(f'Backup created: {backup}')
try:
    con.execute('BEGIN IMMEDIATE')
    total=0.0
    for r in selected:
        # Revalidate under write lock so concurrent/previous actions are not repeated.
        check=con.execute('SELECT credits_activated,hours_total,package_type FROM student_packages WHERE id=? AND student_id=?',(r['id'],a.student_id)).fetchone()
        ledger_count=con.execute("SELECT COUNT(*) FROM credit_ledger WHERE student_id=? AND kind='package_activation' AND note LIKE ?",(a.student_id,f'%purchase #{r["id"]})%')).fetchone()[0]
        if not check or int(check['credits_activated'] or 0)!=0 or ledger_count!=0 or (check['package_type'] or 'lesson')!='lesson':
            raise RuntimeError(f'Purchase #{r["id"]} changed or already credited; rolling back')
        hours=float(check['hours_total'] or 0)
        con.execute('UPDATE student_packages SET credits_activated=1,hours_remaining=? WHERE id=? AND credits_activated=0',(hours,r['id']))
        con.execute('UPDATE students SET credits=credits+? WHERE user_id=?',(hours,a.student_id))
        con.execute('INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)',
                    (a.student_id,hours,'package_activation',f'v13 historical repair: {r["package_name"]} (purchase #{r["id"]})',datetime.datetime.now().isoformat()))
        total+=hours
    con.commit()
    updated=con.execute('SELECT credits FROM students WHERE user_id=?',(a.student_id,)).fetchone()['credits']
    print(f'APPLIED: {len(selected)} purchases, +{total} credits; new balance={updated}; backup={backup}')
except Exception:
    con.rollback(); raise
finally:
    con.close()
