"""One-time authorized pilot reset; fail closed on any unexpected schema."""
import os,sqlite3,tarfile,hashlib,json,time,fcntl
from pathlib import Path
KEEP={1:("admin@kiteclub.gr","admin"),2:("student@kiteclub.gr","student"),3:("angelos@kiteclub.gr","instructor"),4:("thanos@kiteclub.gr","instructor"),5:("konstantinos@kiteclub.gr","instructor"),26:("qa-stripe@kiteclub.gr","student")}
PRESERVE={"users","students","instructors","oauth_identities","spots","skills","packages","app_meta","legal_documents","equipment_items","equipment_history","student_registrations","registration_legal_acceptances","registration_email_confirmations","password_session_versions"}
CLEAR={"booking_audit","booking_merges","booking_participants","booking_slots","bookings","credit_ledger","day_columns","day_hours","day_spots","instructor_hours","instructor_payments","lesson_debts","lesson_payments","login_attempts","messages","package_cancellations","package_payment_requests","package_usage","payment_requests","registration_purchase_context","slots","stripe_test_orders","stripe_test_refund_totals","stripe_test_refunds","student_groups","student_packages","student_payments","student_photos","student_skill_history","student_skill_progress","password_reset_tokens"}
def reset(database,uploads,root):
    root=Path(root); backup=root/"pilot-cleanup-backup-20261109"; backup.mkdir(exist_ok=True)
    with open(backup/"lock","a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        con=sqlite3.connect(database,timeout=60)
        try:
            if con.execute("SELECT value FROM app_meta WHERE key='pilot_reset_20261109'").fetchone():
                return
            actual={r[0]:(r[1],r[2]) for r in con.execute("SELECT id,email,role FROM users WHERE id IN (1,2,3,4,5,26)")}
            assert actual==KEEP,"Retained identities changed"
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            assert tables==PRESERVE|CLEAR,("Unexpected schema",tables^(PRESERVE|CLEAR))
            assert con.execute("PRAGMA integrity_check").fetchall()==[("ok",)]
            snap=backup/"kiteclub.db"
            assert not snap.exists(),"Backup already exists without reset marker; review required"
            with sqlite3.connect(snap) as dest: con.backup(dest); assert dest.execute("PRAGMA integrity_check").fetchall()==[("ok",)]
            files=[p for p in Path(uploads).rglob("*") if p.is_file()]
            manifest={"database_sha256":hashlib.sha256(snap.read_bytes()).hexdigest(),"files":{}}
            with tarfile.open(backup/"uploads.tar.gz","w:gz") as tar:
                for p in files:
                    assert not p.is_symlink()
                    name=str(p.relative_to(uploads)); digest=hashlib.sha256(p.read_bytes()).hexdigest()
                    tar.add(p,arcname=name); assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
                    manifest["files"][name]=digest
            with tarfile.open(backup/"uploads.tar.gz") as tar:
                for name,digest in manifest["files"].items(): assert hashlib.sha256(tar.extractfile(name).read()).hexdigest()==digest
            (backup/"manifest.json").write_text(json.dumps(manifest))
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            before={t:con.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables}
            identity_before=con.execute("SELECT * FROM oauth_identities WHERE user_id IN (1,2,3,4,5,26)").fetchall()
            for t in CLEAR: con.execute('DELETE FROM "'+t+'"')
            for t in ("student_registrations","registration_legal_acceptances","registration_email_confirmations","password_session_versions","oauth_identities","students","instructors"):
                con.execute('DELETE FROM "'+t+'" WHERE user_id NOT IN (1,2,3,4,5,26)')
            con.execute("UPDATE student_registrations SET approved_by=NULL WHERE approved_by NOT IN (1,2,3,4,5,26)")
            con.execute("UPDATE equipment_history SET actor_id=NULL WHERE actor_id NOT IN (1,2,3,4,5,26)")
            con.execute("DELETE FROM users WHERE id NOT IN (1,2,3,4,5,26)")
            con.execute("UPDATE students SET credits=0,level='Beginner',lesson_type='private',group_id=NULL,crew_member=0,crew_start_date=NULL,crew_end_date=NULL,crew_fee=0")
            # Keep the retained instructors' profile images; remove all student/past-user images.
            retained={r[0] for r in con.execute("SELECT profile_photo FROM users WHERE profile_photo IS NOT NULL")}
            con.execute("UPDATE users SET profile_photo=NULL WHERE role='student'")
            assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0]==6
            assert con.execute("SELECT COUNT(*) FROM students").fetchone()[0]==2
            assert con.execute("SELECT COUNT(*) FROM instructors").fetchone()[0]==3
            assert con.execute("PRAGMA foreign_key_check").fetchall()==[]
            assert con.execute("SELECT * FROM oauth_identities WHERE user_id IN (1,2,3,4,5,26)").fetchall()==identity_before
            con.execute("INSERT INTO app_meta(key,value) VALUES('pilot_reset_20261109','done')")
            after={t:con.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables}
            # Quarantine files outside uploads before commit; restore them if transaction fails.
            quarantine=backup/"removed_uploads"; moved=[]
            try:
                for p in files:
                    if "uploads/"+str(p.relative_to(uploads)) not in retained:
                        target=quarantine/p.relative_to(uploads); target.parent.mkdir(parents=True,exist_ok=True)
                        p.rename(target); moved.append((p,target))
                con.commit()
            except Exception:
                con.rollback()
                for p,target in reversed(moved): target.rename(p)
                raise
            (backup/"result.json").write_text(json.dumps({"before":before,"after":after,"backup":str(backup),"integrity_check":[r[0] for r in con.execute("PRAGMA integrity_check")],"foreign_key_check":con.execute("PRAGMA foreign_key_check").fetchall()}))
        except Exception:
            con.rollback(); raise
        finally: con.close()
def setup_pilot_reset(database,uploads,root):
    if os.getenv("PILOT_RESET_APPROVED")=="six-accounts-20261109":
        reset(database,uploads,root)
