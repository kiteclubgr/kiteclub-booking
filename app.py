
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
import sqlite3, os, smtplib, secrets, hmac, time, logging, re, math
from email.message import EmailMessage
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "KiteClub v75.2 · Finance & Student Fix v12"

# v70: production-ready storage. Locally everything stays inside the project.
# On Railway mount a persistent volume at /data and set DATA_DIR=/data.
DATA_DIR_ENV = os.getenv("DATA_DIR", "").strip()
if DATA_DIR_ENV:
    DATA_ROOT = Path(DATA_DIR_ENV).expanduser().resolve()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DB = str(DATA_ROOT / "kiteclub.db")
    UPLOAD_ROOT = DATA_ROOT / "uploads"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    # Existing templates use /static/uploads/... URLs. Keep that URL stable while
    # storing the actual files on the persistent Railway volume.
    static_uploads = Path(BASE) / "static" / "uploads"
    try:
        if static_uploads.is_symlink():
            if static_uploads.resolve() != UPLOAD_ROOT:
                static_uploads.unlink()
        elif static_uploads.exists() and static_uploads.is_dir() and not any(static_uploads.iterdir()):
            static_uploads.rmdir()
        if not static_uploads.exists():
            static_uploads.symlink_to(UPLOAD_ROOT, target_is_directory=True)
    except OSError:
        # Local Windows fallback: keep uploads working even if symlinks are blocked.
        UPLOAD_ROOT = Path(BASE) / "static" / "uploads"
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
else:
    DB = os.path.join(BASE, "kiteclub.db")
    UPLOAD_ROOT = Path(BASE) / "static" / "uploads"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
# Demo-ready build: automatically seed a new, empty database unless explicitly disabled.
# Never use this public-demo configuration with real customer information.
IS_PRODUCTION = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PRODUCTION", "").lower() in ("1", "true", "yes"))
DEMO_MODE = os.getenv("ENABLE_DEMO_DATA", "1").lower() in ("1", "true", "yes")
secret = os.getenv("SECRET_KEY", "").strip()
if not secret:
    # On Railway, keep the generated signing key on the persistent volume when available.
    # Local builds use a gitignored secret file in the project directory.
    key_root = DATA_ROOT if DATA_DIR_ENV else Path(BASE)
    local_key = key_root / ".local_secret_key"
    if local_key.exists():
        secret = local_key.read_text().strip()
    else:
        generated = secrets.token_urlsafe(48)
        try:
            fd = os.open(str(local_key), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as key_file:
                key_file.write(generated)
            secret = generated
        except FileExistsError:
            secret = local_key.read_text().strip()
if len(secret) < 32:
    raise RuntimeError("SECRET_KEY must have at least 32 characters")
app.secret_key = secret
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
# Keep logins stable while testing on desktop and phone.
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION or os.getenv("COOKIE_SECURE", "0").lower() in ("1", "true", "yes"),
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
)


# v75: server-side CSRF protection for all state-changing browser requests.
# Tokens belong to the signed session and are embedded into every POST form.
def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]

app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["payment_request_id"] = lambda: secrets.token_urlsafe(24)

@app.before_request
def enforce_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        supplied = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf_token", "")
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            abort(400, description="Invalid or missing security token. Refresh the page and try again.")

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store" if session.get("uid") else "no-cache"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Login throttling in SQLite, shared between gunicorn workers and restarts.
def login_locked(con, key):
    cutoff = int(time.time()) - 900
    row = con.execute("SELECT attempts, first_at FROM login_attempts WHERE identity=?", (key,)).fetchone()
    return bool(row and row["first_at"] >= cutoff and row["attempts"] >= 8)

def record_login_failure(con, key):
    cutoff = int(time.time()) - 900
    now = int(time.time())
    con.execute("""INSERT INTO login_attempts(identity, attempts, first_at)
      VALUES (?,1,?) ON CONFLICT(identity) DO UPDATE SET
      attempts=CASE WHEN first_at < ? THEN 1 ELSE attempts+1 END,
      first_at=CASE WHEN first_at < ? THEN ? ELSE first_at END""", (key,now,cutoff,cutoff,now))
    con.commit()

@app.template_filter("gr_date")
def gr_date(value):
    """Display ISO YYYY-MM-DD as DD/MM/YYYY."""
    if not value:
        return ""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return value

@app.template_filter("hm24")
def hm24(value):
    """Display time consistently in 24-hour HH:MM form."""
    if not value:
        return ""
    try:
        return datetime.strptime(str(value)[:5], "%H:%M").strftime("%H:%M")
    except Exception:
        return str(value)[:5]

@app.template_filter("gr_long_date")
def gr_long_date(value):
    """Display ISO date as e.g. Τετάρτη 7 Οκτωβρίου."""
    if not value:
        return ""
    try:
        d=datetime.strptime(str(value)[:10], "%Y-%m-%d")
        days=["Δευτέρα","Τρίτη","Τετάρτη","Πέμπτη","Παρασκευή","Σάββατο","Κυριακή"]
        months=["","Ιανουαρίου","Φεβρουαρίου","Μαρτίου","Απριλίου","Μαΐου","Ιουνίου",
                "Ιουλίου","Αυγούστου","Σεπτεμβρίου","Οκτωβρίου","Νοεμβρίου","Δεκεμβρίου"]
        return f"{days[d.weekday()]} {d.day} {months[d.month]}"
    except Exception:
        return value

def crew_season_for_date(value=None):
    """Return the fixed Crew season (May 1 -> Apr 30) containing the given date."""
    if value is None:
        d=datetime.now().date()
    elif hasattr(value, "year") and hasattr(value, "month"):
        d=value
    else:
        d=datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    start_year=d.year if d.month >= 5 else d.year-1
    return f"{start_year:04d}-05-01", f"{start_year+1:04d}-04-30"

def db():
    con = sqlite3.connect(DB, timeout=15)
    con.execute("PRAGMA busy_timeout=15000")
    con.row_factory = sqlite3.Row
    return con

# v71: Beginner curriculum and automatic Beginner -> Kiter progression.
# The higher categories (Intermediate / Expert) are intentionally left manual
# until their technique lists are defined in a later version.
BEGINNER_CURRICULUM = [
    {"number": 1, "title": "Level 1", "usual_hours": "Συνήθως στις πρώτες 2 ώρες", "skills": [
        ("l1_theory", "Θεωρία"),
        ("l1_trim", "Τριμάρισμα"),
        ("l1_control", "Χειρισμός"),
        ("l1_quick_release", "Quick Release"),
        ("l1_power_strike", "Power Strike"),
        ("l1_bodydrag", "Bodydrag"),
    ]},
    {"number": 2, "title": "Level 2", "usual_hours": "", "skills": [
        ("l2_control", "Χειρισμός 2"),
        ("l2_water_relaunch", "Water Relaunch"),
        ("l2_bodydrag", "Bodydrag 2"),
        ("l2_self_rescue", "Self Rescue"),
    ]},
    {"number": 3, "title": "Level 3", "usual_hours": "", "skills": [
        ("l3_control", "Χειρισμός 3"),
        ("l3_bodydrag_downwind", "Bodydrag Downwind"),
        ("l3_bodydrag_upwind", "Bodydrag Upwind"),
        ("l3_bodydrag_board", "Bodydrag with Board"),
    ]},
    {"number": 4, "title": "Level 4", "usual_hours": "", "skills": [
        ("l4_bodydrag", "Bodydrag 4"),
        ("l4_waterstart", "Waterstart"),
        ("l4_keep_going", "Keep Going"),
        ("l4_upwind", "Upwind"),
    ]},
]
BEGINNER_SKILL_LOOKUP = {key: name for level in BEGINNER_CURRICULUM for key, name in level["skills"]}
PROGRESS_STATUSES = {"not_started", "practicing", "mastered"}

def get_student_progress(con, student_id):
    rows=con.execute("""
      SELECT p.skill_key,p.status,p.updated_at,p.updated_by,u.name updater_name,u.surname updater_surname
      FROM student_skill_progress p
      LEFT JOIN users u ON u.id=p.updated_by
      WHERE p.student_id=?
    """,(student_id,)).fetchall()
    saved={r["skill_key"]:dict(r) for r in rows}
    levels=[]; total_mastered=0; total_skills=0
    for level in BEGINNER_CURRICULUM:
        skills=[]; mastered=0
        for key,name in level["skills"]:
            row=saved.get(key,{})
            status=row.get("status") or "not_started"
            if status not in PROGRESS_STATUSES: status="not_started"
            if status=="mastered": mastered+=1
            skills.append({
              "key":key,"name":name,"status":status,
              "updated_at":row.get("updated_at"),
              "updater_name":row.get("updater_name"),
              "updater_surname":row.get("updater_surname"),
            })
        count=len(skills); total_skills+=count; total_mastered+=mastered
        levels.append({
          "number":level["number"],"title":level["title"],"usual_hours":level["usual_hours"],
          "skills":skills,"mastered":mastered,"count":count,"complete":mastered==count
        })
    percent=round((total_mastered/total_skills)*100) if total_skills else 0
    complete=total_skills>0 and total_mastered==total_skills
    return {
      "levels":levels,"total_mastered":total_mastered,"total_skills":total_skills,
      "percent":percent,"complete":complete,
      # v72: while the advanced curricula are not defined, the visible school level
      # is driven by the Beginner programme itself.
      "current_level":"Kiter" if complete else "Beginner"
    }

def students_with_progress_levels(con, rows):
    """Expose the same live level used by student/admin/instructor profiles.

    Do not trust the legacy students.level field for list display.
    """
    return [dict(row, level=get_student_progress(con, row["id"])["current_level"])
            for row in rows]


def set_student_skill_progress(con, student_id, skill_key, status, changed_by):
    if skill_key not in BEGINNER_SKILL_LOOKUP or status not in PROGRESS_STATUSES:
        raise ValueError("Μη έγκυρη τεχνική ή κατάσταση προόδου.")
    old=con.execute("SELECT status FROM student_skill_progress WHERE student_id=? AND skill_key=?",(student_id,skill_key)).fetchone()
    old_status=old["status"] if old else "not_started"
    now=datetime.now().isoformat()
    if old:
        con.execute("UPDATE student_skill_progress SET status=?,updated_at=?,updated_by=? WHERE student_id=? AND skill_key=?",(status,now,changed_by,student_id,skill_key))
    else:
        con.execute("INSERT INTO student_skill_progress(student_id,skill_key,status,updated_at,updated_by) VALUES(?,?,?,?,?)",(student_id,skill_key,status,now,changed_by))
    if old_status!=status:
        con.execute("INSERT INTO student_skill_history(student_id,skill_key,old_status,new_status,changed_at,changed_by) VALUES(?,?,?,?,?,?)",(student_id,skill_key,old_status,status,now,changed_by))
    current=con.execute("SELECT level FROM students WHERE user_id=?",(student_id,)).fetchone()
    before=(current["level"] if current else "Beginner") or "Beginner"
    progress=get_student_progress(con,student_id)
    # Only Beginner/Kiter is automated in v71. Do not overwrite future/manual higher levels.
    after=before
    if before in ("Beginner","Kiter"):
        after="Kiter" if progress["complete"] else "Beginner"
        con.execute("UPDATE students SET level=? WHERE user_id=?",(after,student_id))
    return before,after,progress

def send_email(to_email, subject, body):
    host=os.getenv("SMTP_HOST")
    if not host:
        print("EMAIL PREVIEW:", to_email, subject, body)
        return
    msg=EmailMessage()
    msg["From"]=os.getenv("SMTP_FROM","booking@kiteclub.gr")
    msg["To"]=to_email
    msg["Subject"]=subject
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT","587"))) as s:
        s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        s.send_message(msg)


def password_meets_policy(password):
    """Regular passwords: simple but reasonable policy for local/demo usage."""
    password=(password or "")
    return len(password) >= 8 and any(ch.isalpha() for ch in password) and any(ch.isdigit() for ch in password)


def password_policy_message():
    return "Ο κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες και να περιέχει γράμματα και αριθμούς."


def live_level_case(student_id_expr):
    return f"""(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key)
      FROM student_skill_progress spp
      WHERE spp.student_id={student_id_expr}
        AND spp.status='mastered'
        AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18
      THEN 'Kiter' ELSE 'Beginner' END)"""


def booking_state_meta(status, payment_status=None):
    status=(status or "").strip()
    payment_status=(payment_status or "").strip()
    if status=="completed":
        return {"label":"Completed","class":"completed"}
    if status=="no_show":
        return {"label":"No-show","class":"noshow"}
    if status.startswith("cancelled"):
        return {"label":"Cancelled","class":"cancelled"}
    if status=="pending_payment" or payment_status=="pending":
        return {"label":"Pending payment","class":"pending"}
    return {"label":"Booked","class":"booked"}


def log_booking_audit(con, booking_id, event_type, summary, actor_id=None, actor_role=None, details=""):
    con.execute("""
      INSERT INTO booking_audit(booking_id,actor_id,actor_role,event_type,summary,details,created_at)
      VALUES(?,?,?,?,?,?,?)
    """,(booking_id,actor_id,actor_role,event_type,summary,(details or ""),datetime.now().isoformat()))


def get_booking_audit(con, booking_id, limit=100):
    return con.execute("""
      SELECT ba.*,u.name actor_name,u.surname actor_surname
      FROM booking_audit ba
      LEFT JOIN users u ON u.id=ba.actor_id
      WHERE ba.booking_id=?
      ORDER BY ba.created_at DESC, ba.id DESC
      LIMIT ?
    """,(booking_id,limit)).fetchall()


def ensure_column(con, table, column, definition):
    cols=[r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    con=db(); c=con.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, phone TEXT,
      role TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS students(
      user_id INTEGER PRIMARY KEY, credits REAL DEFAULT 0, level TEXT DEFAULT 'Beginner'
    );
    CREATE TABLE IF NOT EXISTS instructors(
      user_id INTEGER PRIMARY KEY, hourly_rate REAL DEFAULT 15, priority INTEGER DEFAULT 1,
      activation_threshold REAL DEFAULT 4
    );
    CREATE TABLE IF NOT EXISTS spots(
      id INTEGER PRIMARY KEY, name TEXT, info TEXT, map_url TEXT
    );
    CREATE TABLE IF NOT EXISTS slots(
      id INTEGER PRIMARY KEY, lesson_date TEXT, start_time TEXT, duration REAL DEFAULT 1,
      instructor_id INTEGER, spot_id INTEGER, status TEXT DEFAULT 'open'
    );
    CREATE TABLE IF NOT EXISTS bookings(
      id INTEGER PRIMARY KEY, slot_id INTEGER, student_id INTEGER, duration REAL DEFAULT 1,
      status TEXT DEFAULT 'confirmed', payment_status TEXT DEFAULT 'credit',
      amount REAL DEFAULT 0, created_at TEXT, completed_at TEXT, next_skill TEXT
    );
    CREATE TABLE IF NOT EXISTS credit_ledger(
      id INTEGER PRIMARY KEY, student_id INTEGER, booking_id INTEGER, amount REAL,
      kind TEXT, note TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS instructor_hours(
      id INTEGER PRIMARY KEY, instructor_id INTEGER, booking_id INTEGER, hours REAL,
      lesson_date TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS booking_slots(
      booking_id INTEGER NOT NULL,
      slot_id INTEGER NOT NULL,
      PRIMARY KEY(booking_id,slot_id)
    );
    CREATE TABLE IF NOT EXISTS skills(
      id INTEGER PRIMARY KEY, name TEXT UNIQUE, notes TEXT, video_url TEXT
    );
    CREATE TABLE IF NOT EXISTS day_hours(
      id INTEGER PRIMARY KEY,
      lesson_date TEXT NOT NULL,
      start_time TEXT NOT NULL,
      spot_id INTEGER NOT NULL,
      UNIQUE(lesson_date,start_time,spot_id)
    );
    CREATE TABLE IF NOT EXISTS day_columns(
      id INTEGER PRIMARY KEY,
      lesson_date TEXT NOT NULL,
      column_no INTEGER NOT NULL,
      instructor_id INTEGER,
      UNIQUE(lesson_date,column_no)
    );
    CREATE TABLE IF NOT EXISTS day_spots(
      lesson_date TEXT PRIMARY KEY,
      spot_id INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS booking_audit(
      id INTEGER PRIMARY KEY,
      booking_id INTEGER NOT NULL,
      actor_id INTEGER,
      actor_role TEXT,
      event_type TEXT NOT NULL,
      summary TEXT NOT NULL,
      details TEXT,
      created_at TEXT NOT NULL
    );
    """)
    con.commit()

    # Backfill legacy bookings into booking_slots.
    legacy=con.execute("SELECT id,slot_id,duration FROM bookings").fetchall()
    for b in legacy:
        con.execute("INSERT OR IGNORE INTO booking_slots(booking_id,slot_id) VALUES(?,?)",(b["id"],b["slot_id"]))
        if float(b["duration"] or 1) >= 2:
            first=con.execute("SELECT lesson_date,start_time,instructor_id FROM slots WHERE id=?",(b["slot_id"],)).fetchone()
            if first:
                nxt=(datetime.strptime(first["start_time"],"%H:%M")+timedelta(hours=1)).strftime("%H:%M")
                s2=con.execute("""
                  SELECT id FROM slots
                  WHERE lesson_date=? AND start_time=? AND instructor_id=?
                """,(first["lesson_date"],nxt,first["instructor_id"])).fetchone()
                if s2:
                    con.execute("INSERT OR IGNORE INTO booking_slots(booking_id,slot_id) VALUES(?,?)",(b["id"],s2["id"]))
    con.commit()

    ensure_column(con,"users","profile_photo","TEXT")
    ensure_column(con,"users","surname","TEXT")
    ensure_column(con,"users","instagram","TEXT")
    # v50: stable visible Student ID + fixed 2P/3P group links.
    ensure_column(con,"students","student_code","TEXT")
    ensure_column(con,"students","lesson_type","TEXT DEFAULT 'private'")
    ensure_column(con,"students","group_id","INTEGER")
    # v57: optional annual Crew Membership for students.
    ensure_column(con,"students","crew_member","INTEGER DEFAULT 0")
    ensure_column(con,"students","crew_start_date","TEXT")
    ensure_column(con,"students","crew_end_date","TEXT")
    ensure_column(con,"students","crew_fee","REAL DEFAULT 0")
    ensure_column(con,"bookings","instructor_notes","TEXT")
    ensure_column(con,"bookings","no_show_at","TEXT")
    ensure_column(con,"slots","manual_override","TEXT")
    # v42: per-day, per-column activation control. activation_override is
    # NULL for automatic cascade, "active" for forced open, and "standby"
    # for forced standby. activated_once makes an automatic activation sticky
    # so a later cancellation does not unexpectedly close the next instructor.
    ensure_column(con,"day_columns","activation_override","TEXT")
    ensure_column(con,"day_columns","activated_once","INTEGER DEFAULT 0")
    con.execute("""
      CREATE TABLE IF NOT EXISTS app_meta(
        key TEXT PRIMARY KEY,
        value TEXT
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS instructor_payments(
        id INTEGER PRIMARY KEY,
        instructor_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_date TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
      )
    """)
    # v48: package catalog, student purchases/payments and per-booking package usage.
    con.execute("""
      CREATE TABLE IF NOT EXISTS packages(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        hours REAL NOT NULL,
        price REAL NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS student_packages(
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL,
        package_id INTEGER,
        package_name TEXT NOT NULL,
        hours_total REAL NOT NULL,
        hours_remaining REAL NOT NULL DEFAULT 0,
        price REAL NOT NULL DEFAULT 0,
        payment_status TEXT NOT NULL DEFAULT 'paid',
        purchased_at TEXT NOT NULL,
        paid_at TEXT,
        note TEXT
      )
    """)
    # v60: package kinds. Lesson packages carry credits; Crew packages carry a fixed May-April membership season.
    ensure_column(con,"packages","package_type","TEXT DEFAULT 'lesson'")
    ensure_column(con,"student_packages","package_type","TEXT DEFAULT 'lesson'")
    ensure_column(con,"student_packages","valid_from","TEXT")
    ensure_column(con,"student_packages","valid_until","TEXT")
    # v62: payment accounting is independent from lesson completion.
    ensure_column(con,"packages","activation_rule","TEXT DEFAULT 'paid_only'")
    ensure_column(con,"student_packages","activation_rule","TEXT DEFAULT 'paid_only'")
    ensure_column(con,"student_packages","paid_amount","REAL DEFAULT 0")
    ensure_column(con,"student_packages","credits_activated","INTEGER DEFAULT 0")
    con.execute("""
      CREATE TABLE IF NOT EXISTS student_payments(
        id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, purchase_id INTEGER NOT NULL,
        amount REAL NOT NULL, payment_date TEXT NOT NULL, method TEXT, note TEXT, created_at TEXT NOT NULL
      )
    """)
    # v7: create the idempotency ledger during startup/migration, not during
    # a payment POST, so no schema DDL runs in the payment transaction.
    con.execute("""
      CREATE TABLE IF NOT EXISTS package_payment_requests (
        request_id TEXT PRIMARY KEY,
        purchase_id INTEGER NOT NULL,
        created_at TEXT NOT NULL
      )
    """)
    con.execute("""
      UPDATE student_packages
      SET paid_amount=CASE WHEN payment_status='paid' THEN price ELSE COALESCE(paid_amount,0) END,
          credits_activated=CASE WHEN payment_status='paid' AND COALESCE(package_type,'lesson')='lesson' THEN 1 ELSE COALESCE(credits_activated,0) END
    """)

    con.execute("""
      CREATE TABLE IF NOT EXISTS package_usage(
        id INTEGER PRIMARY KEY,
        student_package_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        booking_id INTEGER,
        amount REAL NOT NULL,
        kind TEXT NOT NULL,
        created_at TEXT NOT NULL
      )
    """)
    # v62 standard services for new students.
    standard_services=[("1 ώρα",1.0,60.0,"immediate"),("2 ώρες",2.0,110.0,"immediate"),("Πακέτο 8 ωρών",8.0,360.0,"first_payment")]
    for pname,phours,pprice,rule in standard_services:
        row=con.execute("SELECT id FROM packages WHERE COALESCE(package_type,'lesson')='lesson' AND hours=? AND price=? LIMIT 1",(phours,pprice)).fetchone()
        if row:
            con.execute("UPDATE packages SET activation_rule=? WHERE id=?",(rule,row["id"]))
        else:
            con.execute("INSERT INTO packages(name,hours,price,active,created_at,package_type,activation_rule) VALUES(?,?,?,?,?,?,?)",(pname,phours,pprice,1,datetime.now().isoformat(),"lesson",rule))

    # v64: lesson-photo gallery per student.
    con.execute("""
      CREATE TABLE IF NOT EXISTS student_photos(
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        caption TEXT,
        photo_date TEXT,
        created_at TEXT NOT NULL
      )
    """)
    # v69: in-app Admin <-> Student messages.
    con.execute("""
      CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY,
        sender_id INTEGER NOT NULL,
        recipient_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        read_at TEXT
      )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender_id,recipient_id,created_at)")

    # v71: per-student Beginner curriculum progress + audit trail.
    con.execute("""
      CREATE TABLE IF NOT EXISTS student_skill_progress(
        student_id INTEGER NOT NULL,
        skill_key TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'not_started',
        updated_at TEXT,
        updated_by INTEGER,
        PRIMARY KEY(student_id,skill_key)
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS student_skill_history(
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL,
        skill_key TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT NOT NULL,
        changed_at TEXT NOT NULL,
        changed_by INTEGER
      )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_student_skill_history_student ON student_skill_history(student_id,changed_at)")
    # The school now uses exactly Beginner, Kiter, Intermediate, Expert.
    con.execute("UPDATE students SET level='Expert' WHERE level='Advanced'")

    # v50: groups are internal only; the Admin sees member names, never Group A/B labels.
    con.execute("""
      CREATE TABLE IF NOT EXISTS student_groups(
        id INTEGER PRIMARY KEY,
        group_size INTEGER NOT NULL,
        created_at TEXT NOT NULL
      )
    """)
    # One booking occupies one instructor slot, while all group members are attached here.
    con.execute("""
      CREATE TABLE IF NOT EXISTS booking_participants(
        booking_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        payment_status TEXT NOT NULL DEFAULT 'credit',
        amount REAL NOT NULL DEFAULT 0,
        credit_charged REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        PRIMARY KEY(booking_id,student_id)
      )
    """)
    # v51: each member of a fixed group can finish the same shared lesson differently.
    ensure_column(con,"booking_participants","attendance_status","TEXT")
    ensure_column(con,"booking_participants","attendance_at","TEXT")
    ensure_column(con,"booking_participants","participant_next_skill","TEXT")
    ensure_column(con,"booking_participants","participant_notes","TEXT")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_students_student_code ON students(student_code) WHERE student_code IS NOT NULL")
    # Backfill every legacy/private booking so all booking queries can use one participant model.
    con.execute("""
      INSERT OR IGNORE INTO booking_participants(booking_id,student_id,payment_status,amount,credit_charged,created_at)
      SELECT b.id,b.student_id,COALESCE(b.payment_status,'credit'),COALESCE(b.amount,0),
             CASE WHEN b.payment_status='credit' AND b.status IN ('confirmed','completed','no_show') THEN COALESCE(b.duration,1) ELSE 0 END,
             COALESCE(b.created_at,?)
      FROM bookings b
    """,(datetime.now().isoformat(),))
    # Existing terminal lessons keep their historical result after the v51 migration.
    con.execute("""
      UPDATE booking_participants
      SET attendance_status=(SELECT b.status FROM bookings b WHERE b.id=booking_participants.booking_id),
          attendance_at=COALESCE(attendance_at,(SELECT COALESCE(b.completed_at,b.no_show_at) FROM bookings b WHERE b.id=booking_participants.booking_id)),
          participant_next_skill=COALESCE(participant_next_skill,(SELECT b.next_skill FROM bookings b WHERE b.id=booking_participants.booking_id)),
          participant_notes=COALESCE(participant_notes,(SELECT b.instructor_notes FROM bookings b WHERE b.id=booking_participants.booking_id))
      WHERE attendance_status IS NULL
        AND (SELECT b.status FROM bookings b WHERE b.id=booking_participants.booking_id) IN ('completed','no_show')
    """)
    # Assign permanent human-readable IDs to all existing students.
    used=[]
    for r in con.execute("SELECT student_code FROM students WHERE student_code IS NOT NULL AND student_code<>''").fetchall():
        try: used.append(int(str(r["student_code"]).split('-')[-1]))
        except Exception: pass
    next_code=(max(used) if used else 0)+1
    for r in con.execute("SELECT user_id FROM students WHERE student_code IS NULL OR student_code='' ORDER BY user_id").fetchall():
        con.execute("UPDATE students SET student_code=? WHERE user_id=?",(f"STU-{next_code:04d}",r["user_id"]))
        next_code+=1
    con.commit()

    con.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
        identity TEXT PRIMARY KEY, attempts INTEGER NOT NULL, first_at INTEGER NOT NULL
    )""")
    con.commit()
    # Demo accounts only by explicit opt-in. Production bootstraps with provided credentials.
    if c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"] == 0 and DEMO_MODE:
        users=[
          ("Admin","admin@kiteclub.gr","", "admin","admin123"),
          ("Γιάννης","student@kiteclub.gr","6900000000","student","student123"),
          ("Άγγελος K.","angelos@kiteclub.gr","","instructor","teacher123"),
          ("Sani","sani@kiteclub.gr","","instructor","teacher123"),
          ("Κωνσταντίνος K.","konstantinos@kiteclub.gr","","instructor","teacher123"),
        ]
        for name,email,phone,role,pw in users:
            c.execute("INSERT INTO users(name,email,phone,role,password_hash) VALUES(?,?,?,?,?)",
                      (name,email,phone,role,generate_password_hash(pw)))
        ids={r["email"]:r["id"] for r in c.execute("SELECT id,email FROM users")}
        c.execute("INSERT INTO students(user_id,credits,level) VALUES(?,?,?)",(ids["student@kiteclub.gr"],6,"Intermediate"))
        c.executemany("INSERT INTO instructors(user_id,hourly_rate,priority,activation_threshold) VALUES(?,?,?,?)",[
          (ids["angelos@kiteclub.gr"],15,1,4),
          (ids["sani@kiteclub.gr"],15,2,4),
          (ids["konstantinos@kiteclub.gr"],15,3,4),
        ])
        c.executemany("INSERT INTO spots(name,info,map_url) VALUES(?,?,?)",[
          ("Ωρωπός","Θερμικές συνθήκες, ανοιχτό νερό και μεγάλη παραλία. Συνάντηση στο σημείο που θα επιβεβαιωθεί στο email.","https://maps.google.com/?q=Oropos+Greece"),
          ("Νησάκια Λούτσας","Σταθερός βόρειος άνεμος. Το ακριβές σημείο συνάντησης επιβεβαιώνεται πριν το μάθημα.","https://maps.google.com/?q=Nissakia+Loutsa+Greece"),
          ("Σχινιάς","Μεγάλη παραλία και κατάλληλες συνθήκες κυρίως τους ψυχρότερους μήνες.","https://maps.google.com/?q=Schinias+Greece"),
        ])
        c.executemany("INSERT INTO skills(name,notes,video_url) VALUES(?,?,?)",[
          ("Kite Control","Επανάληψη wind window, launch/landing και σταθερού ελέγχου του kite.","https://www.youtube.com/"),
          ("Body Drag","Δούλεψε σωστή θέση σώματος και κατεύθυνση με μία σταθερή πορεία.","https://www.youtube.com/"),
          ("Water Start","Επανάλαβε τη θέση σανίδας, power stroke και σωστό timing.","https://www.youtube.com/"),
          ("Upwind","Εστίασε σε edge control, θέση λεκάνης και σταθερό kite.","https://www.youtube.com/"),
          ("Transitions","Δούλεψε έλεγχο ταχύτητας, αλλαγή κατεύθυνσης και kite movement.","https://www.youtube.com/"),
        ])
        con.commit()
        # Seed tomorrow-ish demo date based on current day
        day=(datetime.now()+timedelta(days=1)).date().isoformat()
        inst=[r["user_id"] for r in c.execute("SELECT user_id FROM instructors ORDER BY priority")]
        spot=c.execute("SELECT id FROM spots WHERE name='Ωρωπός'").fetchone()["id"]
        for i,h in enumerate(range(11,20)):
            # First instructor open all day
            c.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES(?,?,?,?,?)",
                      (day,f"{h:02d}:00",inst[0],spot,"open"))
            # Second available but managed
            c.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES(?,?,?,?,?)",
                      (day,f"{h:02d}:00",inst[1],spot,"open" if i in [1,2,3,5,6] else "closed"))
            # Third standby
            c.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES(?,?,?,?,?)",
                      (day,f"{h:02d}:00",inst[2],spot,"standby"))
        con.commit()

    # v40 migration: sequential instructor activation uses 4 booked hours by default.
    migrated=con.execute("SELECT value FROM app_meta WHERE key='v40_activation_threshold'").fetchone()
    if not migrated:
        con.execute("UPDATE instructors SET activation_threshold=4")
        # Preserve legacy manual statuses. Open/standby remain automatic unless changed from now on.
        con.execute("""
          UPDATE slots
          SET manual_override=status
          WHERE manual_override IS NULL
            AND status IN ('closed','pending_payment')
        """)
        con.execute("""
          UPDATE slots
          SET manual_override='booked'
          WHERE manual_override IS NULL
            AND status='booked'
            AND NOT EXISTS(
              SELECT 1
              FROM booking_slots bs
              JOIN bookings b ON b.id=bs.booking_id
              WHERE bs.slot_id=slots.id
                AND b.status IN ('confirmed','pending_payment','completed','no_show')
            )
        """)
        con.execute("INSERT INTO app_meta(key,value) VALUES('v40_activation_threshold','4')")
        con.commit()

    # v47 demo/test data: give surnames only to the known built-in demo accounts
    # and add a few extra demo students. User-created accounts are never renamed.
    migrated_v47=con.execute("SELECT value FROM app_meta WHERE key='v47_demo_students_and_surnames'").fetchone()
    if not migrated_v47 and DEMO_MODE:
        demo_identity_updates=[
          ("Γιάννης","Κοτσιράς","student@kiteclub.gr"),
          ("Άγγελος","Καραγιάννης","angelos@kiteclub.gr"),
          ("Sani","Μανώλη","sani@kiteclub.gr"),
          ("Κωνσταντίνος","Νικολάου","konstantinos@kiteclub.gr"),
        ]
        for first_name,surname,email in demo_identity_updates:
            con.execute("""
              UPDATE users
              SET name=?, surname=?
              WHERE email=?
            """,(first_name,surname,email))

        demo_students=[
          ("Μαρία","Παπαδοπούλου","maria.demo@kiteclub.gr","6900000001",8.0,"Intermediate"),
          ("Νίκος","Αντωνίου","nikos.demo@kiteclub.gr","6900000002",4.0,"Beginner"),
          ("Ελένη","Γεωργίου","eleni.demo@kiteclub.gr","6900000003",10.0,"Expert"),
          ("Κώστας","Δημητρίου","kostas.demo@kiteclub.gr","6900000004",6.0,"Intermediate"),
          ("Σοφία","Νικολάου","sofia.demo@kiteclub.gr","6900000005",5.0,"Beginner"),
          ("Αλέξης","Μπουρνάζος","alexis.demo@kiteclub.gr","6900000006",7.0,"Intermediate"),
        ]
        for first_name,surname,email,phone,credits,level in demo_students:
            row=con.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone()
            if row:
                uid=row["id"]
            else:
                cur=con.execute("""
                  INSERT INTO users(name,surname,email,phone,role,password_hash,active)
                  VALUES(?,?,?,?,?,?,1)
                """,(first_name,surname,email,phone,"student",generate_password_hash("student123")))
                uid=cur.lastrowid
            con.execute("""
              INSERT OR IGNORE INTO students(user_id,credits,level) VALUES(?,?,?)
            """,(uid,credits,level))

        con.execute("INSERT INTO app_meta(key,value) VALUES('v47_demo_students_and_surnames','1')")
        con.commit()

    # v50 final pass: students created by seed/migrations in this same startup also
    # receive a permanent public Student ID immediately (no restart required).
    existing_codes=[]
    for r in con.execute("SELECT student_code FROM students WHERE student_code IS NOT NULL AND student_code<>''").fetchall():
        try:
            existing_codes.append(int(str(r["student_code"]).split('-')[-1]))
        except Exception:
            pass
    next_student_number=(max(existing_codes) if existing_codes else 0)+1
    for r in con.execute("SELECT user_id FROM students WHERE student_code IS NULL OR student_code='' ORDER BY user_id").fetchall():
        con.execute("UPDATE students SET student_code=? WHERE user_id=?",(f"STU-{next_student_number:04d}",r["user_id"]))
        next_student_number+=1
    con.commit()
    if con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0:
        admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        if not admin_email or not password_meets_policy(admin_password):
            con.close()
            raise RuntimeError("Empty database: set ADMIN_EMAIL and ADMIN_PASSWORD (8+ chars with letters and numbers), or ENABLE_DEMO_DATA=1 for local demo")
        con.execute("INSERT INTO users(name,email,phone,role,password_hash) VALUES(?,?,?,?,?)",
                    ("Admin", admin_email, "", "admin", generate_password_hash(admin_password)))
        con.commit()
    con.close()



def _next_student_code(con):
    """Return the next permanent public Student ID (STU-0001, STU-0002, ...)."""
    rows=con.execute("SELECT student_code FROM students WHERE student_code IS NOT NULL AND student_code<>''").fetchall()
    nums=[]
    for row in rows:
        try:
            nums.append(int(str(row["student_code"]).split("-")[-1]))
        except Exception:
            pass
    return f"STU-{(max(nums) if nums else 0)+1:04d}"


def _group_participant_ids(con, student_id):
    """Return the fixed booking participants for a student (private=1, 2P=2, 3P=3)."""
    st=con.execute("SELECT user_id,lesson_type,group_id FROM students WHERE user_id=?",(student_id,)).fetchone()
    if not st:
        return []
    lesson_type=(st["lesson_type"] or "private").lower()
    expected={"2p":2,"3p":3}.get(lesson_type,1)
    if expected==1 or not st["group_id"]:
        return [student_id]
    rows=con.execute("""
      SELECT s.user_id
      FROM students s JOIN users u ON u.id=s.user_id
      WHERE s.group_id=? AND COALESCE(u.active,1)=1
      ORDER BY s.user_id
    """,(st["group_id"],)).fetchall()
    ids=[r["user_id"] for r in rows]
    return ids if len(ids)==expected else [student_id]


def _group_members(con, student_id):
    ids=_group_participant_ids(con,student_id)
    if not ids:
        return []
    q=",".join("?" for _ in ids)
    rows=con.execute(f"""
      SELECT u.id,u.name,u.surname,u.email,u.phone,u.profile_photo,
             s.student_code,s.lesson_type,s.group_id,s.level,s.credits
      FROM users u JOIN students s ON s.user_id=u.id
      WHERE u.id IN ({q})
      ORDER BY CASE WHEN u.id=? THEN 0 ELSE 1 END,u.name,u.surname
    """,(*ids,student_id)).fetchall()
    return students_with_progress_levels(con, rows)


def _set_student_group(con, student_id, lesson_type, partner_ids):
    """Synchronize a fixed 2P/3P group across every selected member."""
    lesson_type=(lesson_type or "private").strip().lower()
    if lesson_type not in ("private","2p","3p"):
        lesson_type="private"
    expected={"private":1,"2p":2,"3p":3}[lesson_type]
    current=con.execute("SELECT group_id FROM students WHERE user_id=?",(student_id,)).fetchone()
    if not current:
        raise ValueError("Ο μαθητής δεν βρέθηκε.")
    current_gid=current["group_id"]

    if lesson_type=="private":
        if current_gid:
            con.execute("UPDATE students SET lesson_type='private',group_id=NULL WHERE group_id=?",(current_gid,))
            con.execute("DELETE FROM student_groups WHERE id=?",(current_gid,))
        else:
            con.execute("UPDATE students SET lesson_type='private',group_id=NULL WHERE user_id=?",(student_id,))
        return

    cleaned=[]
    for raw in partner_ids:
        try: pid=int(raw)
        except (TypeError,ValueError): continue
        if pid!=student_id and pid not in cleaned:
            cleaned.append(pid)
    if len(cleaned)!=(expected-1):
        raise ValueError(f"Για {lesson_type.upper()} Group πρέπει να επιλέξεις ακριβώς {expected-1} {'άτομο' if expected==2 else 'άτομα'}.")

    selected=[student_id]+cleaned
    q=",".join("?" for _ in selected)
    rows=con.execute(f"SELECT user_id,group_id FROM students WHERE user_id IN ({q})",selected).fetchall()
    if len(rows)!=expected:
        raise ValueError("Ένα από τα επιλεγμένα άτομα δεν είναι ενεργός μαθητής.")
    for row in rows:
        gid=row["group_id"]
        if gid and gid!=current_gid:
            raise ValueError("Ένα από τα επιλεγμένα άτομα ανήκει ήδη σε άλλο σταθερό group.")

    if current_gid:
        gid=current_gid
        # Any old member removed from the group automatically becomes Private.
        con.execute("UPDATE students SET lesson_type='private',group_id=NULL WHERE group_id=?",(gid,))
        con.execute("UPDATE student_groups SET group_size=? WHERE id=?",(expected,gid))
    else:
        cur=con.execute("INSERT INTO student_groups(group_size,created_at) VALUES(?,?)",(expected,datetime.now().isoformat()))
        gid=cur.lastrowid
    con.executemany("UPDATE students SET lesson_type=?,group_id=? WHERE user_id=?",[(lesson_type,gid,sid) for sid in selected])


def _booking_participants(con, booking_id):
    return con.execute("""
      SELECT bp.*,u.name,u.surname,u.email,u.phone,s.student_code,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=bp.student_id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) AS level,s.credits,s.lesson_type,s.group_id
      FROM booking_participants bp
      JOIN users u ON u.id=bp.student_id
      LEFT JOIN students s ON s.user_id=bp.student_id
      WHERE bp.booking_id=?
      ORDER BY bp.student_id
    """,(booking_id,)).fetchall()


def _charge_booking_participants(con, booking_id, participant_ids, duration, force_pending=False, note_prefix="Booking reservation"):
    """Charge each group member independently while the instructor slot is reserved only once."""
    duration=float(duration or 1)
    any_pending=False
    total_pending=0.0
    now=datetime.now().isoformat()
    for sid in participant_ids:
        row=con.execute("SELECT credits FROM students WHERE user_id=?",(sid,)).fetchone()
        credits=float(row["credits"] or 0) if row else 0.0
        if not force_pending and credits>=duration:
            pay="credit"; amount=0.0; charged=duration
            con.execute("UPDATE students SET credits=credits-? WHERE user_id=?",(duration,sid))
            con.execute("""
              INSERT INTO credit_ledger(student_id,booking_id,amount,kind,note,created_at)
              VALUES(?,?,?,?,?,?)
            """,(sid,booking_id,-duration,"reserve",f"{note_prefix} #{booking_id}",now))
            _consume_package_hours(con,sid,booking_id,duration)
        else:
            pay="pending"; amount=(110.0 if abs(duration-2.0)<0.01 else 60.0*duration); charged=0.0
            any_pending=True; total_pending+=amount
        con.execute("""
          INSERT OR REPLACE INTO booking_participants(booking_id,student_id,payment_status,amount,credit_charged,created_at)
          VALUES(?,?,?,?,?,?)
        """,(booking_id,sid,pay,amount,charged,now))
    status="pending_payment" if any_pending else "confirmed"
    payment="pending" if any_pending else "credit"
    return status,payment,total_pending


def _refund_one_booking_participant(con, booking_id, student_id, kind="makeup_refund", note="Make-up credit returned"):
    """Return only this participant's charged credit for a shared/group booking."""
    row=con.execute("SELECT credit_charged FROM booking_participants WHERE booking_id=? AND student_id=?",(booking_id,student_id)).fetchone()
    hours=float(row["credit_charged"] or 0) if row else 0.0
    if hours<=0:
        # A pending participant was never charged; clear any pending amount for Make-up.
        con.execute("UPDATE booking_participants SET payment_status='makeup',amount=0,credit_charged=0 WHERE booking_id=? AND student_id=?",(booking_id,student_id))
        return 0.0
    now=datetime.now().isoformat()
    con.execute("UPDATE students SET credits=credits+? WHERE user_id=?",(hours,student_id))
    con.execute("""
      INSERT INTO credit_ledger(student_id,booking_id,amount,kind,note,created_at)
      VALUES(?,?,?,?,?,?)
    """,(student_id,booking_id,hours,kind,f"{note} #{booking_id}",now))
    _refund_package_hours(con,student_id,booking_id,hours)
    con.execute("UPDATE booking_participants SET payment_status='makeup',amount=0,credit_charged=0 WHERE booking_id=? AND student_id=?",(booking_id,student_id))
    return hours


def _refund_booking_participants(con, booking_id, kind="booking_refund", note="Booking refund"):
    """Refund only participant credits actually charged for this booking; safe to call once."""
    rows=con.execute("SELECT student_id,credit_charged FROM booking_participants WHERE booking_id=?",(booking_id,)).fetchall()
    total=0.0
    now=datetime.now().isoformat()
    for row in rows:
        hours=float(row["credit_charged"] or 0)
        if hours<=0:
            continue
        sid=row["student_id"]
        con.execute("UPDATE students SET credits=credits+? WHERE user_id=?",(hours,sid))
        con.execute("""
          INSERT INTO credit_ledger(student_id,booking_id,amount,kind,note,created_at)
          VALUES(?,?,?,?,?,?)
        """,(sid,booking_id,hours,kind,f"{note} #{booking_id}",now))
        _refund_package_hours(con,sid,booking_id,hours)
        con.execute("UPDATE booking_participants SET credit_charged=0 WHERE booking_id=? AND student_id=?",(booking_id,sid))
        total+=hours
    return total

def _booked_hours_for_instructor(con, lesson_date, instructor_id):
    """Reserved instructor workload hours for the activation cascade.

    A physical slot counts once even when several students share the same
    instructor/hour (manual shared theory or a fixed group booking).
    """
    actual=con.execute("""
      SELECT COALESCE(SUM(x.duration),0) h
      FROM (
        SELECT DISTINCT s.id,s.duration
        FROM slots s
        JOIN booking_slots bs ON bs.slot_id=s.id
        JOIN bookings b ON b.id=bs.booking_id
        WHERE s.lesson_date=? AND s.instructor_id=?
          AND b.status IN ('confirmed','pending_payment','completed','no_show')
      ) x
    """,(lesson_date,instructor_id)).fetchone()["h"] or 0

    manual=con.execute("""
      SELECT COALESCE(SUM(s.duration),0) h
      FROM slots s
      WHERE s.lesson_date=? AND s.instructor_id=?
        AND s.status IN ('booked','pending_payment')
        AND NOT EXISTS(
          SELECT 1
          FROM booking_slots bs
          JOIN bookings b ON b.id=bs.booking_id
          WHERE bs.slot_id=s.id
            AND b.status IN ('confirmed','pending_payment','completed','no_show')
        )
    """,(lesson_date,instructor_id)).fetchone()["h"] or 0
    return float(actual)+float(manual)


def _unlogged_instructor_hours_for_booking(con, instructor_id, booking_id):
    """Return only physical slot-hours not already credited to this instructor.

    This prevents 2-3 students sharing one instructor/hour from multiplying
    instructor worked hours while each student still keeps an independent booking.
    """
    current=con.execute("""
      SELECT DISTINCT s.id,s.duration
      FROM booking_slots bs
      JOIN slots s ON s.id=bs.slot_id
      WHERE bs.booking_id=? AND s.instructor_id=?
    """,(booking_id,instructor_id)).fetchall()
    if not current:
        current=con.execute("""
          SELECT DISTINCT s.id,s.duration
          FROM bookings b JOIN slots s ON s.id=b.slot_id
          WHERE b.id=? AND s.instructor_id=?
        """,(booking_id,instructor_id)).fetchall()
    if not current:
        return 0.0
    logged={r["slot_id"] for r in con.execute("""
      SELECT DISTINCT bs.slot_id
      FROM instructor_hours ih
      JOIN booking_slots bs ON bs.booking_id=ih.booking_id
      WHERE ih.instructor_id=?
    """,(instructor_id,)).fetchall()}
    return float(sum(float(r["duration"] or 1) for r in current if r["id"] not in logged))


def _student_time_conflict(con, student_id, lesson_date, start_time, exclude_booking_id=None):
    """Return an active booking for the same participant at the same date/time, if any."""
    sql="""
      SELECT DISTINCT b.id
      FROM bookings b
      JOIN booking_participants bp ON bp.booking_id=b.id
      JOIN booking_slots bs ON bs.booking_id=b.id
      JOIN slots occupied ON occupied.id=bs.slot_id
      WHERE bp.student_id=?
        AND occupied.lesson_date=?
        AND occupied.start_time=?
        AND b.status IN ('confirmed','pending_payment','completed','no_show')
    """
    params=[student_id,lesson_date,start_time]
    if exclude_booking_id is not None:
        sql += " AND b.id<>?"
        params.append(exclude_booking_id)
    sql += " LIMIT 1"
    return con.execute(sql,params).fetchone()


def _instructor_time_conflict(con, instructor_id, lesson_date, start_time, exclude_booking_id=None):
    """Guard against duplicate timetable rows creating two lessons for one instructor at once."""
    sql="""
      SELECT DISTINCT b.id
      FROM bookings b
      JOIN booking_slots bs ON bs.booking_id=b.id
      JOIN slots occupied ON occupied.id=bs.slot_id
      WHERE occupied.instructor_id=?
        AND occupied.lesson_date=?
        AND occupied.start_time=?
        AND b.status IN ('confirmed','pending_payment','completed','no_show')
    """
    params=[instructor_id,lesson_date,start_time]
    if exclude_booking_id is not None:
        sql += " AND b.id<>?"
        params.append(exclude_booking_id)
    sql += " LIMIT 1"
    return con.execute(sql,params).fetchone()


def _activate_student_purchase(con, purchase, reason="purchase activation"):
    if not purchase or int(purchase["credits_activated"] or 0)==1 or (purchase["package_type"] or "lesson")=="crew":
        return 0.0
    hours=float(purchase["hours_total"] or 0)
    if hours<=0: return 0.0
    con.execute("UPDATE students SET credits=credits+? WHERE user_id=?",(hours,purchase["student_id"]))
    con.execute("UPDATE student_packages SET hours_remaining=?,credits_activated=1 WHERE id=?",(hours,purchase["id"]))
    con.execute("INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",(purchase["student_id"],hours,"package_activation",f"{reason}: {purchase['package_name']} (purchase #{purchase['id']})",datetime.now().isoformat()))
    return hours

def _purchase_payment_status(price, paid_amount):
    price=float(price or 0); paid=float(paid_amount or 0)
    if paid<=0: return "unpaid"
    if paid+1e-9>=price: return "paid"
    return "partial"

def _consume_package_hours(con, student_id, booking_id, hours):
    """Consume paid package hours FIFO. Manual credits can still cover any remainder."""
    remaining=max(0.0,float(hours or 0))
    if remaining<=0:
        return 0.0
    rows=con.execute("""
      SELECT id,hours_remaining
      FROM student_packages
      WHERE student_id=? AND COALESCE(credits_activated,0)=1 AND hours_remaining>0
      ORDER BY purchased_at,id
    """,(student_id,)).fetchall()
    used=0.0
    for row in rows:
        if remaining<=0:
            break
        available=float(row["hours_remaining"] or 0)
        take=min(available,remaining)
        if take<=0:
            continue
        con.execute("UPDATE student_packages SET hours_remaining=hours_remaining-? WHERE id=?",(take,row["id"]))
        con.execute("""
          INSERT INTO package_usage(student_package_id,student_id,booking_id,amount,kind,created_at)
          VALUES(?,?,?,?,?,?)
        """,(row["id"],student_id,booking_id,-take,"booking_use",datetime.now().isoformat()))
        used+=take
        remaining-=take
    return used


def _refund_package_hours(con, student_id, booking_id, hours=None):
    """Restore only package hours actually consumed by this booking."""
    rows=con.execute("""
      SELECT student_package_id, SUM(amount) net_amount
      FROM package_usage
      WHERE student_id=? AND booking_id=?
      GROUP BY student_package_id
      HAVING SUM(amount)<0
      ORDER BY student_package_id
    """,(student_id,booking_id)).fetchall()
    remaining=None if hours is None else max(0.0,float(hours or 0))
    restored=0.0
    for row in rows:
        refundable=max(0.0,-float(row["net_amount"] or 0))
        if remaining is not None:
            refundable=min(refundable,remaining)
        if refundable<=0:
            continue
        con.execute("UPDATE student_packages SET hours_remaining=hours_remaining+? WHERE id=?",(refundable,row["student_package_id"]))
        con.execute("""
          INSERT INTO package_usage(student_package_id,student_id,booking_id,amount,kind,created_at)
          VALUES(?,?,?,?,?,?)
        """,(row["student_package_id"],student_id,booking_id,refundable,"booking_refund",datetime.now().isoformat()))
        restored+=refundable
        if remaining is not None:
            remaining-=refundable
            if remaining<=0:
                break
    return restored


def get_day_activation_state(lesson_date):
    """Return activation state in the exact order of Admin Slot columns."""
    con=db()
    cols=con.execute("""
      SELECT dc.column_no,dc.instructor_id,
             TRIM(COALESCE(u.name,'') || ' ' || COALESCE(u.surname,'')) instructor_name,
             COALESCE(i.activation_threshold,4) threshold,
             dc.activation_override,COALESCE(dc.activated_once,0) activated_once
      FROM day_columns dc
      JOIN users u ON u.id=dc.instructor_id
      LEFT JOIN instructors i ON i.user_id=dc.instructor_id
      WHERE dc.lesson_date=? AND dc.instructor_id IS NOT NULL
      ORDER BY dc.column_no
    """,(lesson_date,)).fetchall()

    states=[]
    previous_active=True
    previous_hours=None
    previous_threshold=None
    previous_name=None
    for idx,col in enumerate(cols):
        booked_hours=_booked_hours_for_instructor(con,lesson_date,col["instructor_id"])
        threshold=float(col["threshold"] or 4)
        override=(col["activation_override"] or "").strip().lower() or None
        activated_once=bool(col["activated_once"])

        if idx==0:
            # Slot 1 is the base instructor for the day and is always active.
            active=True
            activation_mode="base"
        elif override=="active":
            active=True
            activation_mode="manual_active"
        elif override=="standby":
            active=False
            activation_mode="manual_standby"
        elif activated_once:
            # Once the automatic 4h rule has opened a column, keep it open even
            # if a previous booking is later cancelled.
            active=True
            activation_mode="sticky_auto"
        else:
            active=bool(previous_active and previous_hours >= previous_threshold)
            activation_mode="auto"

        remaining_hours=0.0
        if idx>0 and previous_threshold is not None and previous_hours is not None:
            remaining_hours=max(0.0,float(previous_threshold)-float(previous_hours))

        states.append({
          "column_no":col["column_no"],
          "instructor_id":col["instructor_id"],
          "instructor_name":col["instructor_name"],
          "booked_hours":booked_hours,
          "threshold":threshold,
          "active":active,
          "activation_mode":activation_mode,
          "activation_override":override,
          "activated_once":activated_once,
          "remaining_hours":remaining_hours,
          "previous_name":previous_name,
          "previous_hours":previous_hours,
          "previous_threshold":previous_threshold
        })
        previous_active=active
        previous_hours=booked_hours
        previous_threshold=threshold
        previous_name=col["instructor_name"]
    con.close()
    return states


def rebalance_instructors(lesson_date):
    """
    Sequential daily activation based on Admin column order.

    Slot 1 is active immediately. Each next instructor normally opens when the
    immediately previous active instructor reaches their booked-hour threshold
    (4h by default). Admin can force a later column ACTIVE or STANDBY. Once an
    instructor has opened automatically, that activation remains sticky even if
    a previous booking is later cancelled. Existing bookings and explicit
    per-slot Admin overrides are never overwritten.
    """
    con=db()
    cols=con.execute("""
      SELECT dc.column_no,dc.instructor_id,COALESCE(i.activation_threshold,4) threshold,
             dc.activation_override,COALESCE(dc.activated_once,0) activated_once
      FROM day_columns dc
      LEFT JOIN instructors i ON i.user_id=dc.instructor_id
      WHERE dc.lesson_date=? AND dc.instructor_id IS NOT NULL
      ORDER BY dc.column_no
    """,(lesson_date,)).fetchall()

    if not cols:
        con.close()
        return

    # Ensure every assigned instructor has a slot for every generated hour.
    hours=con.execute("""
      SELECT start_time,spot_id FROM day_hours
      WHERE lesson_date=? ORDER BY start_time
    """,(lesson_date,)).fetchall()
    for col in cols:
        for h in hours:
            exists=con.execute("""
              SELECT id FROM slots
              WHERE lesson_date=? AND start_time=? AND instructor_id=?
            """,(lesson_date,h["start_time"],col["instructor_id"])).fetchone()
            if not exists:
                con.execute("""
                  INSERT INTO slots(lesson_date,start_time,duration,instructor_id,spot_id,status,manual_override)
                  VALUES(?,?,?,?,?,'standby',NULL)
                """,(lesson_date,h["start_time"],1,col["instructor_id"],h["spot_id"]))

    previous_active=True
    previous_hours=None
    previous_threshold=None
    for idx,col in enumerate(cols):
        override=(col["activation_override"] or "").strip().lower() or None
        activated_once=bool(col["activated_once"])

        if idx==0:
            is_active=True
        elif override=="active":
            is_active=True
        elif override=="standby":
            is_active=False
        elif activated_once:
            is_active=True
        else:
            is_active=bool(previous_active and previous_hours >= previous_threshold)
            if is_active:
                # Remember automatic activation. This prevents a later
                # cancellation from closing slots that students may already be
                # seeing or using on the next instructor.
                con.execute("""
                  UPDATE day_columns SET activated_once=1
                  WHERE lesson_date=? AND column_no=?
                """,(lesson_date,col["column_no"]))
                activated_once=True

        booked_hours=_booked_hours_for_instructor(con,lesson_date,col["instructor_id"])

        slots=con.execute("""
          SELECT s.id,s.status,s.manual_override
          FROM slots s
          WHERE s.lesson_date=? AND s.instructor_id=?
        """,(lesson_date,col["instructor_id"])).fetchall()

        for s in slots:
            has_booking=con.execute("""
              SELECT 1
              FROM booking_slots bs
              JOIN bookings b ON b.id=bs.booking_id
              WHERE bs.slot_id=?
                AND b.status IN ('confirmed','pending_payment','completed','no_show')
              LIMIT 1
            """,(s["id"],)).fetchone()
            if has_booking:
                continue

            # Explicit per-slot Admin override wins over column activation.
            if s["manual_override"]:
                desired=s["manual_override"]
            else:
                desired='open' if is_active else 'standby'
            if s["status"] != desired:
                con.execute("UPDATE slots SET status=? WHERE id=?",(desired,s["id"]))

        previous_active=is_active
        previous_hours=booked_hours
        previous_threshold=float(col["threshold"] or 4)

    con.commit()
    con.close()

def normalize_day_columns(lesson_date):
    """
    Keep each instructor in at most one logical slot column per day.
    If duplicate legacy assignments exist, keep the lowest column number
    and clear later duplicates.
    """
    con=db()
    rows=con.execute("""
      SELECT id,column_no,instructor_id
      FROM day_columns
      WHERE lesson_date=? AND instructor_id IS NOT NULL
      ORDER BY column_no
    """,(lesson_date,)).fetchall()
    seen=set()
    for r in rows:
        iid=r["instructor_id"]
        if iid in seen:
            con.execute("UPDATE day_columns SET instructor_id=NULL WHERE id=?",(r["id"],))
        else:
            seen.add(iid)
    con.commit()
    con.close()



def parse_gr_date(value):
    """Accept DD/MM/YYYY or ISO YYYY-MM-DD and return ISO YYYY-MM-DD."""
    if not value:
        return value
    value=str(value).strip()
    for fmt in ("%d/%m/%Y","%Y-%m-%d"):
        try:
            return datetime.strptime(value,fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError("Invalid date format")



def normalize_selected_instructor_slots(lesson_date):
    """Compatibility shim. v40 activation is handled by rebalance_instructors."""
    return



def repair_booking_slot_links(lesson_date=None):
    """
    Ensure each 1h/2h booking is linked to every hourly slot it occupies.
    Safe to run repeatedly.
    """
    con=db()
    if lesson_date:
        bookings=con.execute("""
          SELECT b.id,b.slot_id,b.duration
          FROM bookings b
          JOIN slots s ON s.id=b.slot_id
          WHERE s.lesson_date=?
        """,(lesson_date,)).fetchall()
    else:
        bookings=con.execute("SELECT id,slot_id,duration FROM bookings").fetchall()

    for b in bookings:
        first=con.execute("""
          SELECT lesson_date,start_time,instructor_id
          FROM slots WHERE id=?
        """,(b["slot_id"],)).fetchone()
        if not first:
            continue

        duration=max(1,int(float(b["duration"] or 1)))
        start_dt=datetime.strptime(first["start_time"],"%H:%M")

        for offset in range(duration):
            t=(start_dt+timedelta(hours=offset)).strftime("%H:%M")
            s=con.execute("""
              SELECT id FROM slots
              WHERE lesson_date=? AND start_time=? AND instructor_id=?
            """,(first["lesson_date"],t,first["instructor_id"])).fetchone()
            if s:
                con.execute("""
                  INSERT OR IGNORE INTO booking_slots(booking_id,slot_id)
                  VALUES(?,?)
                """,(b["id"],s["id"]))
    con.commit()
    con.close()



def sync_day_spot(lesson_date):
    """
    day_spots is the canonical source for a day's spot.
    Keep all day_hours and slots for that date synchronized to it.
    """
    con=db()
    ds=con.execute("SELECT spot_id FROM day_spots WHERE lesson_date=?",(lesson_date,)).fetchone()
    if ds:
        con.execute("UPDATE day_hours SET spot_id=? WHERE lesson_date=?",(ds["spot_id"],lesson_date))
        con.execute("UPDATE slots SET spot_id=? WHERE lesson_date=?",(ds["spot_id"],lesson_date))
        con.commit()
    con.close()



def save_profile_photo(file_storage, user_id):
    if not file_storage or not file_storage.filename:
        return None
    filename=secure_filename(file_storage.filename)
    ext=Path(filename).suffix.lower()
    if ext not in (".jpg",".jpeg",".png",".webp"):
        raise ValueError("Επίτρεπονται μόνο JPG, PNG ή WEBP.")
    final_name=f"user_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{ext}"
    target=UPLOAD_ROOT/final_name
    target.parent.mkdir(parents=True,exist_ok=True)
    file_storage.save(target)
    return f"uploads/{final_name}"


def current_user():
    if not session.get("uid"): return None
    con=db()
    u=con.execute("SELECT * FROM users WHERE id=?",(session["uid"],)).fetchone()
    con.close()
    if u and not u["active"]:
        session.clear()
        return None
    if u:
        # Refresh legacy sessions created before v48 and keep the role available
        # to the shared desktop/mobile navigation.
        session["role"]=u["role"]
        session.permanent=True
    return u

@app.context_processor
def inject():
    me=current_user()
    unread=0
    if me:
        con=db()
        unread=con.execute("SELECT COUNT(*) n FROM messages WHERE recipient_id=? AND read_at IS NULL",(me["id"],)).fetchone()["n"]
        con.close()
    return {"me": me, "message_unread_count": unread, "booking_state_meta": booking_state_meta, "app_version": APP_VERSION}

@app.get("/healthz")
def healthz():
    try:
        con=db(); con.execute("SELECT 1").fetchone(); con.close()
        return {"status": "ok"}, 200
    except Exception:
        return {"status": "error"}, 500


@app.route("/", methods=["GET","POST"])
def login():
    # If a valid session already exists, never show a second login screen just
    # because a stale tab tried to open a page for another role.
    if request.method=="GET":
        existing=current_user()
        if existing:
            return redirect(url_for("home"))
    if request.method=="POST":
        email = request.form.get("email", "").strip().lower()
        key = email[:254]  # Shared failure counter per account; avoids logging passwords.
        con=db()
        if login_locked(con, key):
            con.close()
            flash("Πολλές αποτυχημένες προσπάθειες. Δοκίμασε ξανά σε 15 λεπτά.")
            return render_template("login.html"), 429
        u=con.execute("SELECT * FROM users WHERE lower(email)=? AND COALESCE(active,1)=1",(email,)).fetchone()
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            con.execute("DELETE FROM login_attempts WHERE identity=?", (key,))
            con.commit(); con.close()
            session.clear()
            session["uid"]=u["id"]
            session["role"]=u["role"]
            session.permanent=True
            csrf_token()  # Rotate token with newly authenticated session.
            return redirect(url_for("home"))
        record_login_failure(con, key)
        con.close()
        flash("Λάθος email ή password")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/home")
def home():
    u=current_user()
    if not u: return redirect(url_for("login"))
    if u["role"]=="student": return redirect(url_for("student_home"))
    if u["role"]=="admin": return redirect(url_for("admin"))
    return redirect(url_for("instructor"))


@app.route("/student/home")
def student_home():
    u=current_user()
    if not u or u["role"]!="student": return redirect(url_for("login"))
    con=db()
    st=con.execute("""SELECT s.*,u.name,u.surname,u.email,u.phone,u.instagram,u.profile_photo FROM students s JOIN users u ON u.id=s.user_id WHERE s.user_id=?""",(u["id"],)).fetchone()
    now_dt=datetime.now()
    rows=con.execute("""
      SELECT b.*,COALESCE(bp.attendance_status,b.status) participant_status,sl.lesson_date,sl.start_time,
             ins.name instructor,ins.surname instructor_surname,COALESCE(day_sp.name,slot_sp.name) spot
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users ins ON ins.id=sl.instructor_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE bp.student_id=? ORDER BY sl.lesson_date,sl.start_time
    """,(u["id"],)).fetchall()
    upcoming=[]
    for row in rows:
        try: dt=datetime.strptime(f"{row['lesson_date']} {row['start_time']}","%Y-%m-%d %H:%M")
        except Exception: continue
        status=row["participant_status"] or row["status"]
        if status in ("confirmed","pending_payment") and dt>=now_dt:
            upcoming.append(dict(row))
    photos=con.execute("SELECT * FROM student_photos WHERE student_id=? ORDER BY COALESCE(photo_date,'') DESC,created_at DESC,id DESC LIMIT 6",(u["id"],)).fetchall()
    con.close()
    return render_template("student_home.html",student=st,upcoming=upcoming,student_photos=photos,student_nav="home")

@app.route("/student")
def student():
    u=current_user()
    if not u or u["role"]!="student": return redirect(url_for("login"))

    raw_date=request.args.get("date")
    try:
        date=parse_gr_date(raw_date) if raw_date else (datetime.now()+timedelta(days=1)).date().isoformat()
    except ValueError:
        date=(datetime.now()+timedelta(days=1)).date().isoformat()

    normalize_selected_instructor_slots(date)
    rebalance_instructors(date)
    sync_day_spot(date)
    repair_booking_slot_links(date)
    con=db()
    st=con.execute("""
      SELECT s.*,u.name,u.surname,u.email,u.phone,u.profile_photo
      FROM students s JOIN users u ON u.id=s.user_id
      WHERE s.user_id=?
    """,(u["id"],)).fetchone()
    group_members=_group_members(con,u["id"])

    selected_spot=con.execute("""
      SELECT sp.*
      FROM day_spots ds JOIN spots sp ON sp.id=ds.spot_id
      WHERE ds.lesson_date=?
    """,(date,)).fetchone()
    if not selected_spot:
        selected_spot=con.execute("""
          SELECT sp.*
          FROM day_hours dh JOIN spots sp ON sp.id=dh.spot_id
          WHERE dh.lesson_date=?
          ORDER BY dh.start_time LIMIT 1
        """,(date,)).fetchone()

    # Instructor columns: follow admin day columns, preserving order.
    day_columns=con.execute("""
      SELECT dc.column_no,dc.instructor_id,
             u.name instructor_name,u.surname instructor_surname,
             u.profile_photo instructor_photo
      FROM day_columns dc
      LEFT JOIN users u ON u.id=dc.instructor_id
      WHERE dc.lesson_date=? AND dc.instructor_id IS NOT NULL
      ORDER BY dc.column_no
    """,(date,)).fetchall()

    # Hours come from generated day hours.
    hours=[r["start_time"] for r in con.execute("""
      SELECT start_time FROM day_hours
      WHERE lesson_date=?
      ORDER BY start_time
    """,(date,)).fetchall()]

    # All slots for selected day, including unavailable statuses.
    all_slots=con.execute("""
      SELECT s.*,u.name instructor,u.surname instructor_surname,sp.name spot
      FROM slots s
      JOIN users u ON u.id=s.instructor_id
      JOIN spots sp ON sp.id=s.spot_id
      WHERE s.lesson_date=?
      ORDER BY s.start_time
    """,(date,)).fetchall()

    # Active bookings on the day, mapped to slot.
    booking_rows=con.execute("""
      SELECT b.*,bs.slot_id AS occupied_slot_id,s.start_time,s.instructor_id,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count
      FROM booking_slots bs
      JOIN bookings b ON b.id=bs.booking_id
      JOIN slots s ON s.id=bs.slot_id
      WHERE s.lesson_date=?
        AND b.status IN ('confirmed','pending_payment','completed','no_show')
    """,(date,)).fetchall()
    booking_by_slot={r["occupied_slot_id"]:r for r in booking_rows}
    own_booking_ids={r["booking_id"] for r in con.execute("""
      SELECT DISTINCT bp.booking_id
      FROM booking_participants bp
      JOIN booking_slots bs ON bs.booking_id=bp.booking_id
      JOIN slots sx ON sx.id=bs.slot_id
      WHERE bp.student_id=? AND sx.lesson_date=?
    """,(u["id"],date)).fetchall()}

    # Build matrix by hour + instructor.
    slot_matrix={}
    for s in all_slots:
        b=booking_by_slot.get(s["id"])
        own=bool(b and b["id"] in own_booking_ids)
        effective_status=s["status"]
        if b:
            if b["status"]=="completed":
                effective_status="completed"
            elif b["status"]=="pending_payment" or b["payment_status"]=="pending":
                effective_status="pending_payment"
            else:
                effective_status="booked"

        slot_matrix[(s["start_time"],s["instructor_id"])]={
          "slot":dict(s),
          "booking":dict(b) if b else None,
          "own":own,
          "effective_status":effective_status
        }

    # Weekly calendar.
    selected_dt=datetime.strptime(date,"%Y-%m-%d").date()
    week_start=selected_dt - timedelta(days=selected_dt.weekday())
    greek_days=["Δευτέρα","Τρίτη","Τετάρτη","Πέμπτη","Παρασκευή","Σάββατο","Κυριακή"]
    week_days=[]
    for idx in range(7):
        d=week_start + timedelta(days=idx)
        iso=d.isoformat()
        spotrow=con.execute("""
          SELECT sp.name
          FROM day_spots ds JOIN spots sp ON sp.id=ds.spot_id
          WHERE ds.lesson_date=?
        """,(iso,)).fetchone()
        if not spotrow:
            spotrow=con.execute("""
              SELECT sp.name
              FROM day_hours dh JOIN spots sp ON sp.id=dh.spot_id
              WHERE dh.lesson_date=?
              ORDER BY dh.start_time LIMIT 1
            """,(iso,)).fetchone()
        available=con.execute("""
          SELECT COUNT(*) n FROM slots
          WHERE lesson_date=? AND status='open'
        """,(iso,)).fetchone()["n"]
        week_days.append({
          "iso":iso,
          "label":greek_days[idx],
          "spot":spotrow["name"] if spotrow else None,
          "available":available,
          "has_program":bool(spotrow),
          "selected":iso==date
        })

    prev_week=(week_start-timedelta(days=7)).isoformat()
    next_week=(week_start+timedelta(days=7)).isoformat()
    week_end=(week_start+timedelta(days=6)).isoformat()

    booking_rows=con.execute("""
      SELECT b.*,bp.payment_status participant_payment_status,bp.amount participant_amount,
             COALESCE(bp.attendance_status,b.status) participant_status,
             COALESCE(bp.participant_next_skill,b.next_skill) participant_next_skill,
             COALESCE(bp.participant_notes,b.instructor_notes) participant_notes,
             s.start_time,s.lesson_date,u.name instructor,u.surname instructor_surname,
             COALESCE(day_sp.name,slot_sp.name) spot,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots s ON s.id=b.slot_id
      JOIN users u ON u.id=s.instructor_id
      JOIN spots slot_sp ON slot_sp.id=s.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=s.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE bp.student_id=?
      ORDER BY s.lesson_date DESC,s.start_time DESC
    """,(u["id"],)).fetchall()

    now_dt=datetime.now()
    bookings=[]
    for row in booking_rows:
        item=dict(row)
        try:
            lesson_dt=datetime.strptime(
                f"{row['lesson_date']} {row['start_time']}",
                "%Y-%m-%d %H:%M"
            )
            hours_until=(lesson_dt-now_dt).total_seconds()/3600
        except Exception:
            hours_until=-999

        item["can_cancel"] = (
            row["status"] in ("confirmed","pending_payment")
            and hours_until >= 6
        )
        item["hours_until"] = hours_until
        item["status"] = row["participant_status"] or row["status"]
        item["next_skill"] = row["participant_next_skill"] or row["next_skill"]
        item["instructor_notes"] = row["participant_notes"] or row["instructor_notes"]
        bookings.append(item)

    con.close()
    return render_template(
      "student.html",
      student=st,
      bookings=bookings,
      date=date,
      selected_spot=selected_spot,
      week_days=week_days,
      prev_week=prev_week,
      next_week=next_week,
      week_start=week_start.isoformat(),
      week_end=week_end,
      day_columns=day_columns,
      hours=hours,
      slot_matrix=slot_matrix,
      group_members=group_members
    )


ALLOWED_GALLERY_EXTENSIONS={"jpg","jpeg","png","webp"}

def save_student_gallery_photo(file_obj, student_id):
    if not file_obj or not file_obj.filename:
        return None
    filename=secure_filename(file_obj.filename)
    if "." not in filename or filename.rsplit(".",1)[1].lower() not in ALLOWED_GALLERY_EXTENSIONS:
        raise ValueError("Επιτρέπονται μόνο JPG, PNG και WEBP φωτογραφίες.")
    try:
        pos=file_obj.stream.tell()
        file_obj.stream.seek(0,2)
        size=file_obj.stream.tell()
        file_obj.stream.seek(pos)
    except Exception:
        size=0
    if size and size>10*1024*1024:
        raise ValueError("Κάθε φωτογραφία μπορεί να είναι έως 10MB.")
    ext=filename.rsplit(".",1)[1].lower()
    folder=UPLOAD_ROOT/"student_gallery"/str(student_id)
    folder.mkdir(parents=True,exist_ok=True)
    unique=f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}.{ext}"
    file_obj.save(folder/unique)
    return f"uploads/student_gallery/{student_id}/{unique}"

@app.route("/student/profile")
def student_profile():
    u=current_user()
    if not u or u["role"]!="student": return redirect(url_for("login"))
    con=db()
    st=con.execute("""SELECT s.*,u.name,u.surname,u.email,u.phone,u.instagram,u.profile_photo FROM students s JOIN users u ON u.id=s.user_id WHERE s.user_id=?""",(u["id"],)).fetchone()
    group_members=_group_members(con,u["id"])
    rows=con.execute("""
      SELECT b.*,bp.payment_status participant_payment_status,
             COALESCE(bp.attendance_status,b.status) participant_status,
             COALESCE(bp.participant_next_skill,b.next_skill) participant_next_skill,
             COALESCE(bp.participant_notes,b.instructor_notes) participant_notes,
             sl.lesson_date,sl.start_time,
             ins.name instructor,ins.surname instructor_surname,
             COALESCE(day_sp.name,slot_sp.name) spot,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users ins ON ins.id=sl.instructor_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE bp.student_id=? ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(u["id"],)).fetchall()
    now_dt=datetime.now(); upcoming=[]; completed=[]; cancelled=[]; no_shows=[]; makeups=[]
    completed_hours=0.0; no_show_hours=0.0; makeup_hours=0.0
    for row in rows:
        item=dict(row)
        try: dt=datetime.strptime(f"{row['lesson_date']} {row['start_time']}","%Y-%m-%d %H:%M")
        except Exception: dt=now_dt
        status=row["participant_status"] or row["status"]
        item["status"]=status
        item["next_skill"]=row["participant_next_skill"] or row["next_skill"]
        item["instructor_notes"]=row["participant_notes"] or row["instructor_notes"]
        duration=float(row["duration"] or 0)
        if status=="completed":
            completed_hours+=duration; completed.append(item)
        elif status=="no_show":
            no_show_hours+=duration; no_shows.append(item)
        elif status=="makeup":
            makeup_hours+=duration; makeups.append(item)
        elif str(status).startswith("cancelled"):
            cancelled.append(item)
        elif status in ("confirmed","pending_payment") and dt>=now_dt:
            upcoming.append(item)
    # Upcoming lessons must be chronological, regardless of descending history query.
    upcoming.sort(key=lambda b: (b["lesson_date"], b["start_time"], b["id"]))
    package_history=con.execute("""
      SELECT * FROM student_packages WHERE student_id=?
      ORDER BY purchased_at DESC,id DESC
    """,(u["id"],)).fetchall()
    today_iso=datetime.now().date().isoformat()
    crew_status="inactive"
    if int(st["crew_member"] or 0)==1:
        if st["crew_end_date"] and st["crew_end_date"] < today_iso:
            crew_status="expired"
        elif st["crew_start_date"] and st["crew_start_date"] > today_iso:
            crew_status="scheduled"
        else:
            crew_status="active"
    student_photos=con.execute("""
      SELECT * FROM student_photos WHERE student_id=?
      ORDER BY COALESCE(photo_date,'') DESC, created_at DESC, id DESC
    """,(u["id"],)).fetchall()
    progress=get_student_progress(con,u["id"])
    con.close()
    return render_template(
      "student_profile.html",student=st,upcoming=upcoming,completed=completed,
      cancelled=cancelled,no_shows=no_shows,makeups=makeups,completed_hours=completed_hours,
      no_show_hours=no_show_hours,makeup_hours=makeup_hours,package_history=package_history,group_members=group_members,
      crew_status=crew_status,student_photos=student_photos,progress=progress
    )


@app.route("/student/profile/edit", methods=["GET","POST"])
def student_profile_edit():
    u=current_user()
    if not u or u["role"]!="student":
        return redirect(url_for("login"))

    if request.method=="GET":
        con=db()
        st=con.execute("""SELECT s.*,u.name,u.surname,u.email,u.phone,u.instagram,u.profile_photo FROM students s JOIN users u ON u.id=s.user_id WHERE s.user_id=?""",(u["id"],)).fetchone()
        con.close()
        if not st:
            flash("Δεν βρέθηκε το προφίλ μαθητή.")
            return redirect(url_for("student_profile"))
        return render_template("student_profile_edit.html",student=st)

    name=request.form.get("name","").strip()
    surname=request.form.get("surname","").strip()
    email=request.form.get("email","").strip().lower()
    phone=request.form.get("phone","").strip()
    instagram=request.form.get("instagram","").strip()
    new_password=request.form.get("new_password","")
    confirm_password=request.form.get("confirm_password","")

    if not name or not email:
        flash("Το όνομα και το email είναι υποχρεωτικά.")
        return redirect(url_for("student_profile_edit"))
    if new_password and new_password!=confirm_password:
        flash("Οι κωδικοί δεν ταιριάζουν.")
        return redirect(url_for("student_profile_edit"))
    if new_password and not password_meets_policy(new_password):
        flash(password_policy_message())
        return redirect(url_for("student_profile_edit"))

    con=db(); con.execute("BEGIN IMMEDIATE")
    duplicate=con.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND id<>?",(email,u["id"])).fetchone()
    if duplicate:
        con.rollback(); con.close()
        flash("Αυτό το email χρησιμοποιείται ήδη από άλλο λογαριασμό.")
        return redirect(url_for("student_profile_edit"))

    row=con.execute("SELECT profile_photo FROM users WHERE id=?",(u["id"],)).fetchone()
    photo=row["profile_photo"] if row else None
    upload=request.files.get("profile_photo")
    if upload and upload.filename:
        try:
            new_photo=save_profile_photo(upload,u["id"])
            if new_photo:
                photo=new_photo
        except Exception as e:
            con.rollback(); con.close()
            flash(f"Δεν έγινε αποθήκευση φωτογραφίας: {e}")
            return redirect(url_for("student_profile_edit"))

    con.execute("UPDATE users SET name=?,surname=?,email=?,phone=?,instagram=?,profile_photo=? WHERE id=?",
                (name,surname,email,phone,instagram,photo,u["id"]))
    if new_password:
        con.execute("UPDATE users SET password_hash=? WHERE id=?",(generate_password_hash(new_password),u["id"]))
    con.commit(); con.close()
    flash("Το προφίλ ενημερώθηκε.")
    return redirect(url_for("student_profile"))

@app.post("/book/<int:slot_id>")
def book(slot_id):
    u=current_user()
    if not u or u["role"]!="student": return redirect(url_for("login"))
    try:
        duration=float(request.form.get("duration","1"))
    except (TypeError,ValueError):
        duration=1.0
    if duration not in (1.0,2.0):
        flash("Η διάρκεια μπορεί να είναι 1 ή 2 ώρες.")
        return redirect(url_for("student"))

    con=db(); con.execute("BEGIN IMMEDIATE")
    slot=con.execute("SELECT * FROM slots WHERE id=?",(slot_id,)).fetchone()
    st=con.execute("SELECT * FROM students WHERE user_id=?",(u["id"],)).fetchone()
    if not slot or slot["status"]!="open" or not st:
        con.rollback(); con.close(); flash("Το slot δεν είναι πλέον διαθέσιμο."); return redirect(url_for("student"))

    participant_ids=_group_participant_ids(con,u["id"])
    expected={"2p":2,"3p":3}.get((st["lesson_type"] or "private").lower(),1)
    if len(participant_ids)!=expected:
        con.rollback(); con.close()
        flash("Το group σου δεν είναι σωστά ρυθμισμένο. Επικοινώνησε με τη σχολή.")
        return redirect(url_for("student",date=slot["lesson_date"]))

    # Need contiguous slot if 2h.
    chosen=[slot]
    if duration==2:
        t=datetime.strptime(slot["start_time"],"%H:%M")+timedelta(hours=1)
        nxt=con.execute("SELECT * FROM slots WHERE lesson_date=? AND start_time=? AND instructor_id=? AND status='open'",
          (slot["lesson_date"],t.strftime("%H:%M"),slot["instructor_id"])).fetchone()
        if not nxt:
            con.rollback(); con.close(); flash("Δεν υπάρχουν δύο συνεχόμενες ώρες."); return redirect(url_for("student",date=slot["lesson_date"]))
        chosen.append(nxt)

    # Every fixed group member must be free at the selected time.
    for target in chosen:
        for sid in participant_ids:
            if _student_time_conflict(con,sid,target["lesson_date"],target["start_time"]):
                person=con.execute("SELECT name,surname FROM users WHERE id=?",(sid,)).fetchone()
                pname=((person["name"] or "") + ((" " + person["surname"]) if person and person["surname"] else "")) if person else "Μέλος του group"
                con.rollback(); con.close()
                flash(f"Ο/Η {pname} έχει ήδη κράτηση στις {target['start_time']}.")
                return redirect(url_for("student",date=target["lesson_date"]))
        if _instructor_time_conflict(con,target["instructor_id"],target["lesson_date"],target["start_time"]):
            con.rollback(); con.close()
            flash("Ο instructor έχει ήδη μάθημα αυτή την ώρα.")
            return redirect(url_for("student",date=target["lesson_date"]))

    # One booking reserves the instructor slot. Participants are attached separately.
    cur=con.execute("""
      INSERT INTO bookings(slot_id,student_id,duration,status,payment_status,amount,created_at)
      VALUES(?,?,?,'confirmed','credit',0,?)
    """,(slot_id,u["id"],duration,datetime.now().isoformat()))
    bid=cur.lastrowid
    status,pay,amount=_charge_booking_participants(con,bid,participant_ids,duration,note_prefix="Group/private booking reservation")
    con.execute("UPDATE bookings SET status=?,payment_status=?,amount=? WHERE id=?",(status,pay,amount,bid))

    for chosen_slot in chosen:
        con.execute("INSERT OR IGNORE INTO booking_slots(booking_id,slot_id) VALUES(?,?)",(bid,chosen_slot["id"]))
        con.execute("UPDATE slots SET status='booked' WHERE id=?",(chosen_slot["id"],))

    sp=con.execute("SELECT sp.* FROM spots sp JOIN slots s ON s.spot_id=sp.id WHERE s.id=?",(slot_id,)).fetchone()
    participants=_booking_participants(con,bid)
    log_booking_audit(con,bid,"created",f"Νέα κράτηση από μαθητή για {slot['lesson_date']} {slot['start_time']} ({duration:g}h).",u["id"],u["role"],f"participants={len(participant_ids)}; payment={pay}; amount={amount}")
    con.commit()
    booked_date=slot["lesson_date"]
    con.close()
    rebalance_instructors(booked_date)

    names=", ".join(((r["name"] or "") + ((" " + r["surname"]) if r["surname"] else "")) for r in participants)
    for person in participants:
        pstatus=person["payment_status"]
        subject="KiteClub — Επιβεβαίωση μαθήματος" if pstatus!="pending" else "KiteClub — Κράτηση σε αναμονή πληρωμής"
        body=(f"Η κράτηση για {names} καταχωρήθηκε για {slot['lesson_date']} στις {slot['start_time']} ({duration:g} ώρες).\n"
              f"Spot: {sp['name']}\n{sp['info']}\nΧάρτης: {sp['map_url']}\n"
              f"Κατάσταση δικής σου συμμετοχής: {'Confirmed' if pstatus!='pending' else 'Pending payment'}")
        if person["email"]:
            send_email(person["email"],subject,body)

    if len(participant_ids)>1:
        flash(f"Η κράτηση καταχωρήθηκε αυτόματα και για τα {len(participant_ids)} μέλη του group." if status=="confirmed" else
              f"Η ώρα δεσμεύτηκε για όλο το group ({len(participant_ids)} άτομα). Υπάρχει τουλάχιστον μία συμμετοχή σε Pending payment.")
    else:
        flash("Η κράτηση καταχωρήθηκε." if status=="confirmed" else "Η ώρα δεσμεύτηκε προσωρινά. Αναμένει πληρωμή.")
    return redirect(url_for("student",date=booked_date))


@app.post("/booking/<int:booking_id>/cancel")
def cancel_student_booking(booking_id):
    u=current_user()
    if not u or u["role"]!="student":
        return redirect(url_for("login"))

    con=db(); con.execute("BEGIN IMMEDIATE")
    b=con.execute("""
      SELECT b.*,s.lesson_date,s.start_time
      FROM bookings b
      JOIN slots s ON s.id=b.slot_id
      JOIN booking_participants bp ON bp.booking_id=b.id
      WHERE b.id=? AND bp.student_id=?
      LIMIT 1
    """,(booking_id,u["id"])).fetchone()

    if not b:
        con.rollback(); con.close()
        flash("Η κράτηση δεν βρέθηκε.")
        return redirect(url_for("student"))

    if b["status"] not in ("confirmed","pending_payment"):
        lesson_date=b["lesson_date"]
        con.rollback(); con.close()
        flash("Η συγκεκριμένη κράτηση δεν μπορεί να ακυρωθεί.")
        return redirect(url_for("student",date=lesson_date))

    lesson_dt=datetime.strptime(f"{b['lesson_date']} {b['start_time']}","%Y-%m-%d %H:%M")
    hours_until=(lesson_dt-datetime.now()).total_seconds()/3600
    if hours_until < 6:
        lesson_date=b["lesson_date"]
        con.rollback(); con.close()
        flash("Η ακύρωση επιτρέπεται μόνο μέχρι 6 ώρες πριν την έναρξη του μαθήματος.")
        return redirect(url_for("student",date=lesson_date))

    participant_count=con.execute("SELECT COUNT(*) n FROM booking_participants WHERE booking_id=?",(booking_id,)).fetchone()["n"]
    # A group booking belongs to the fixed group, so cancellation by any member cancels the shared slot for everyone.
    con.execute("UPDATE bookings SET status='cancelled_student' WHERE id=?",(booking_id,))
    _refund_booking_participants(con,booking_id,"booking_refund","Refund for cancelled booking")
    log_booking_audit(con,booking_id,"cancelled","Ακύρωση κράτησης από μαθητή.",u["id"],u["role"],f"refunded_hours=yes; participants={participant_count}")

    linked=con.execute("SELECT slot_id FROM booking_slots WHERE booking_id=?",(booking_id,)).fetchall()
    for r in linked:
        con.execute("UPDATE slots SET status='open' WHERE id=?",(r["slot_id"],))

    con.commit()
    lesson_date=b["lesson_date"]
    con.close()
    rebalance_instructors(lesson_date)

    if participant_count>1:
        flash("Η group κράτηση ακυρώθηκε για όλα τα μέλη και επιστράφηκαν οι ώρες που είχαν χρεωθεί.")
    else:
        flash("Η κράτηση ακυρώθηκε και οι ώρες επιστράφηκαν στο πακέτο σου.")
    return redirect(url_for("student",date=lesson_date))


@app.route("/messages", methods=["GET","POST"])
def student_messages():
    u=current_user()
    if not u or u["role"]!="student": return redirect(url_for("login"))
    con=db()
    admin_user=con.execute("SELECT * FROM users WHERE role='admin' AND COALESCE(active,1)=1 ORDER BY id LIMIT 1").fetchone()
    if not admin_user:
        con.close(); flash("Δεν υπάρχει διαθέσιμος Admin."); return redirect(url_for("student_home"))
    if request.method=="POST":
        body=(request.form.get("body") or "").strip()
        if body:
            body=body[:2000]
            con.execute("INSERT INTO messages(sender_id,recipient_id,body,created_at) VALUES(?,?,?,?)",(u["id"],admin_user["id"],body,datetime.now().isoformat()))
            con.commit()
        con.close(); return redirect(url_for("student_messages"))
    con.execute("UPDATE messages SET read_at=? WHERE recipient_id=? AND sender_id=? AND read_at IS NULL",(datetime.now().isoformat(),u["id"],admin_user["id"]))
    con.commit()
    thread=con.execute("""
      SELECT m.*,su.name sender_name,su.surname sender_surname
      FROM messages m JOIN users su ON su.id=m.sender_id
      WHERE (m.sender_id=? AND m.recipient_id=?) OR (m.sender_id=? AND m.recipient_id=?)
      ORDER BY m.created_at
    """,(u["id"],admin_user["id"],admin_user["id"],u["id"])).fetchall()
    st=con.execute("SELECT s.*,u.name,u.surname,u.profile_photo FROM students s JOIN users u ON u.id=s.user_id WHERE s.user_id=?",(u["id"],)).fetchone()
    con.close()
    return render_template("student_messages.html",student=st,thread=thread,student_nav="messages")

@app.route("/admin/messages", methods=["GET","POST"])
def admin_messages():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    selected_id=request.args.get("student_id",type=int) or request.form.get("student_id",type=int)
    if request.method=="POST" and selected_id:
        target=con.execute("SELECT id FROM users WHERE id=? AND role='student'",(selected_id,)).fetchone()
        body=(request.form.get("body") or "").strip()
        if target and body:
            con.execute("INSERT INTO messages(sender_id,recipient_id,body,created_at) VALUES(?,?,?,?)",(u["id"],selected_id,body[:2000],datetime.now().isoformat()))
            con.commit()
        con.close(); return redirect(url_for("admin_messages",student_id=selected_id))
    students=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,s.student_code,
             (SELECT COUNT(*) FROM messages m WHERE m.sender_id=u.id AND m.recipient_id=? AND m.read_at IS NULL) unread,
             (SELECT MAX(created_at) FROM messages m WHERE (m.sender_id=u.id AND m.recipient_id=?) OR (m.sender_id=? AND m.recipient_id=u.id)) last_message_at
      FROM users u JOIN students s ON s.user_id=u.id
      WHERE COALESCE(u.active,1)=1
      ORDER BY CASE WHEN last_message_at IS NULL THEN 1 ELSE 0 END,last_message_at DESC,u.name,u.surname
    """,(u["id"],u["id"],u["id"])).fetchall()
    selected=None; thread=[]
    if selected_id:
        selected=con.execute("SELECT u.*,s.student_code FROM users u JOIN students s ON s.user_id=u.id WHERE u.id=?",(selected_id,)).fetchone()
        if selected:
            con.execute("UPDATE messages SET read_at=? WHERE recipient_id=? AND sender_id=? AND read_at IS NULL",(datetime.now().isoformat(),u["id"],selected_id)); con.commit()
            thread=con.execute("""
              SELECT m.*,su.name sender_name,su.surname sender_surname
              FROM messages m JOIN users su ON su.id=m.sender_id
              WHERE (m.sender_id=? AND m.recipient_id=?) OR (m.sender_id=? AND m.recipient_id=?)
              ORDER BY m.created_at
            """,(u["id"],selected_id,selected_id,u["id"])).fetchall()
    con.close()
    return render_template("admin_messages.html",students=students,selected=selected,thread=thread,admin_active="messages")

@app.route("/admin/search")
def admin_global_search():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    q=(request.args.get("q") or "").strip()
    results=[]
    if q:
        like=f"%{q.lower()}%"
        con=db()
        results=con.execute("""
          SELECT u.id,u.name,u.surname,u.email,u.phone,u.role,s.student_code,s.level
          FROM users u LEFT JOIN students s ON s.user_id=u.id
          WHERE COALESCE(u.active,1)=1 AND u.role IN ('student','instructor')
            AND (LOWER(COALESCE(u.name,'')) LIKE ? OR LOWER(COALESCE(u.surname,'')) LIKE ?
                 OR LOWER(COALESCE(u.email,'')) LIKE ? OR LOWER(COALESCE(u.phone,'')) LIKE ?
                 OR LOWER(COALESCE(s.student_code,'')) LIKE ?)
          ORDER BY u.role,u.name,u.surname LIMIT 50
        """,(like,like,like,like,like)).fetchall()
        student_rows=[r for r in results if r['role']=='student']
        student_levels={r['id']:r for r in students_with_progress_levels(con, student_rows)} if student_rows else {}
        results=[dict(r, level=student_levels.get(r['id'],{}).get('level', r['level'])) for r in results]
        con.close()
    return render_template("admin_search.html",q=q,results=results,admin_active="search")

@app.route("/admin")
def admin():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    raw_date=request.args.get("date")
    try:
        date=parse_gr_date(raw_date) if raw_date else (datetime.now()+timedelta(days=1)).date().isoformat()
    except ValueError:
        date=(datetime.now()+timedelta(days=1)).date().isoformat()
        flash("Χρησιμοποίησε ημερομηνία σε μορφή ΗΗ/ΜΜ/ΕΕΕΕ.")
    # v44: the first Admin screen is a real "Today" dashboard.  Keep the
    # selected management date and today's live schedule normalized independently.
    today_date=datetime.now().date().isoformat()
    sync_day_spot(date)
    repair_booking_slot_links(date)
    normalize_day_columns(date)
    normalize_selected_instructor_slots(date)
    rebalance_instructors(date)
    if today_date != date:
        sync_day_spot(today_date)
        repair_booking_slot_links(today_date)
        normalize_day_columns(today_date)
        normalize_selected_instructor_slots(today_date)
        rebalance_instructors(today_date)
    con=db()
    slots=con.execute("""SELECT s.*,u.name instructor,u.surname instructor_surname,sp.name spot FROM slots s JOIN users u ON u.id=s.instructor_id JOIN spots sp ON sp.id=s.spot_id WHERE s.lesson_date=? ORDER BY s.start_time,u.name,u.surname""",(date,)).fetchall()
    bookings=con.execute("""SELECT b.*,su.name student,su.surname student_surname,
             iu.name instructor,iu.surname instructor_surname,s.start_time,s.lesson_date,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM bookings b JOIN users su ON su.id=b.student_id JOIN slots s ON s.id=b.slot_id JOIN users iu ON iu.id=s.instructor_id
      ORDER BY b.id DESC LIMIT 30""").fetchall()
    instructors=con.execute("""SELECT u.id,u.name,u.surname,u.profile_photo,u.email,u.phone,i.*,
      COALESCE(SUM(CASE WHEN ih.lesson_date=? THEN ih.hours ELSE 0 END),0) done_hours,
      COALESCE(SUM(CASE WHEN s.lesson_date=? AND s.status='booked' THEN 1 ELSE 0 END),0) booked_slots,
      CASE WHEN EXISTS(
        SELECT 1 FROM day_columns dc
        WHERE dc.lesson_date=? AND dc.instructor_id=u.id
      ) THEN 1 ELSE 0 END AS selected_today
      FROM instructors i
      JOIN users u ON u.id=i.user_id
      LEFT JOIN instructor_hours ih ON ih.instructor_id=u.id
      LEFT JOIN slots s ON s.instructor_id=u.id
      GROUP BY u.id ORDER BY i.priority""",(date,date,date)).fetchall()
    students=con.execute("""SELECT u.id,u.name,u.surname,u.email,u.phone,s.credits,s.level,
             s.student_code,s.lesson_type,s.group_id
      FROM students s JOIN users u ON u.id=s.user_id ORDER BY u.name,u.surname""").fetchall()
    students=students_with_progress_levels(con, students)
    spots=con.execute("SELECT * FROM spots ORDER BY name").fetchall()
    day_hours=con.execute("""
      SELECT dh.*,sp.name spot
      FROM day_hours dh JOIN spots sp ON sp.id=dh.spot_id
      WHERE dh.lesson_date=?
      ORDER BY dh.start_time
    """,(date,)).fetchall()

    # Ensure 3 logical slot columns exist for this date.
    for col_no in (1,2,3):
        con.execute("INSERT OR IGNORE INTO day_columns(lesson_date,column_no,instructor_id) VALUES(?,?,NULL)",
                    (date,col_no))
    con.commit()

    day_columns=con.execute("""
      SELECT dc.*,u.name instructor_name,u.surname instructor_surname,u.profile_photo instructor_photo
      FROM day_columns dc
      LEFT JOIN users u ON u.id=dc.instructor_id
      WHERE dc.lesson_date=?
      ORDER BY dc.column_no
    """,(date,)).fetchall()

    activation_states=get_day_activation_state(date)
    activation_by_column={s["column_no"]:s for s in activation_states}
    activation_by_instructor={s["instructor_id"]:s for s in activation_states}

    # One spot per day. For legacy dates without day_spots, infer it from the earliest day_hour.
    day_spot=con.execute("""
      SELECT ds.spot_id,sp.name
      FROM day_spots ds JOIN spots sp ON sp.id=ds.spot_id
      WHERE ds.lesson_date=?
    """,(date,)).fetchone()
    if not day_spot and day_hours:
        inferred_spot_id=day_hours[0]["spot_id"]
        con.execute("INSERT OR REPLACE INTO day_spots(lesson_date,spot_id) VALUES(?,?)",(date,inferred_spot_id))
        con.commit()
        day_spot=con.execute("""
          SELECT ds.spot_id,sp.name
          FROM day_spots ds JOIN spots sp ON sp.id=ds.spot_id
          WHERE ds.lesson_date=?
        """,(date,)).fetchone()

    # Weekly calendar (Monday-Sunday) around selected date.
    selected_dt=datetime.strptime(date,"%Y-%m-%d").date()
    week_start=selected_dt - timedelta(days=selected_dt.weekday())
    week_days=[]
    greek_days=["Δευτέρα","Τρίτη","Τετάρτη","Πέμπτη","Παρασκευή","Σάββατο","Κυριακή"]
    for idx in range(7):
        d=week_start + timedelta(days=idx)
        iso=d.isoformat()
        spotrow=con.execute("""
          SELECT sp.name
          FROM day_spots ds JOIN spots sp ON sp.id=ds.spot_id
          WHERE ds.lesson_date=?
        """,(iso,)).fetchone()
        if not spotrow:
            # Legacy fallback: infer from earliest generated hour.
            spotrow=con.execute("""
              SELECT sp.name
              FROM day_hours dh JOIN spots sp ON sp.id=dh.spot_id
              WHERE dh.lesson_date=?
              ORDER BY dh.start_time LIMIT 1
            """,(iso,)).fetchone()
        slot_count=con.execute("""
          SELECT COUNT(*) n FROM slots WHERE lesson_date=?
        """,(iso,)).fetchone()["n"]
        week_days.append({
          "iso":iso,
          "label":greek_days[idx],
          "spot":spotrow["name"] if spotrow else None,
          "slot_count":slot_count,
          "selected": iso==date
        })
    prev_week=(week_start-timedelta(days=7)).isoformat()
    next_week=(week_start+timedelta(days=7)).isoformat()
    week_end=(week_start+timedelta(days=6)).isoformat()

    # Weekly instructor report for the selected admin week.
    report_week_start=selected_dt - timedelta(days=selected_dt.weekday())
    report_week_end=report_week_start + timedelta(days=6)

    instructor_report=[]
    for inst in instructors:
        daily=[]
        total_hours=0.0
        total_lessons=0

        for idx in range(7):
            d=report_week_start + timedelta(days=idx)
            iso=d.isoformat()
            row=con.execute("""
              SELECT COUNT(DISTINCT ih.booking_id) lessons,
                     COALESCE(SUM(ih.hours),0) hours
              FROM instructor_hours ih
              WHERE ih.instructor_id=? AND ih.lesson_date=?
            """,(inst["id"],iso)).fetchone()

            lessons=int(row["lessons"] or 0)
            hrs=float(row["hours"] or 0)
            total_lessons += lessons
            total_hours += hrs
            daily.append({
              "iso":iso,
              "label":greek_days[idx],
              "lessons":lessons,
              "hours":hrs
            })

        instructor_report.append({
          "id":inst["id"],
          "name":((inst["name"] or "") + ((" " + inst["surname"]) if inst["surname"] else "")),
          "hourly_rate":float(inst["hourly_rate"] or 0),
          "total_hours":total_hours,
          "total_lessons":total_lessons,
          "total_pay":total_hours * float(inst["hourly_rate"] or 0),
          "daily":daily
        })

    # Build admin timetable matrix: rows=times, columns=instructors.
    slot_booking_rows=con.execute("""
      SELECT s.id slot_id,b.id booking_id,b.student_id,b.status booking_status,b.payment_status,
             su.name student_name,su.surname student_surname,b.duration,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names,
             base.lesson_date booking_lesson_date,base.start_time booking_start_time,
             base.instructor_id booking_instructor_id
      FROM slots s
      LEFT JOIN booking_slots bs ON bs.slot_id=s.id
      LEFT JOIN bookings b ON b.id=bs.booking_id AND b.status NOT LIKE 'cancelled%'
      LEFT JOIN slots base ON base.id=b.slot_id
      LEFT JOIN users su ON su.id=b.student_id
      WHERE s.lesson_date=?
    """,(date,)).fetchall()
    bookings_by_slot={}
    for r in slot_booking_rows:
        if r["booking_status"]:
            bookings_by_slot.setdefault(r["slot_id"],[]).append(r)
    booking_by_slot={sid:rows[-1] for sid,rows in bookings_by_slot.items()}

    times=sorted({s["start_time"] for s in slots})
    timetable={}
    for t in times:
        timetable[t]={}
    for s in slots:
        timetable.setdefault(s["start_time"],{})[s["instructor_id"]]={
            "slot": s,
            "booking": booking_by_slot.get(s["id"]),
            "bookings": bookings_by_slot.get(s["id"],[]),
            "shared_count": sum(int((r["participant_count"] or 1)) for r in bookings_by_slot.get(s["id"],[]))
        }

    # v44 — Admin "Today" dashboard.
    # The timetable is intentionally instructor-columns first with the time column
    # on the RIGHT, matching the requested operational view.
    today_columns=con.execute("""
      SELECT dc.column_no,dc.instructor_id,u.name instructor_name,u.surname instructor_surname,
             u.profile_photo instructor_photo
      FROM day_columns dc
      LEFT JOIN users u ON u.id=dc.instructor_id
      WHERE dc.lesson_date=? AND dc.instructor_id IS NOT NULL
      ORDER BY dc.column_no
    """,(today_date,)).fetchall()

    today_hours=con.execute("""
      SELECT start_time,spot_id
      FROM day_hours
      WHERE lesson_date=?
      ORDER BY start_time
    """,(today_date,)).fetchall()
    if not today_hours:
        today_hours=con.execute("""
          SELECT DISTINCT start_time,NULL AS spot_id
          FROM slots WHERE lesson_date=? ORDER BY start_time
        """,(today_date,)).fetchall()

    today_slot_rows=con.execute("""
      SELECT s.id slot_id,s.start_time,s.instructor_id,s.status slot_status,s.manual_override,
             b.id booking_id,b.status booking_status,b.payment_status,b.duration,
             base.lesson_date booking_lesson_date,base.start_time booking_start_time,
             base.instructor_id booking_instructor_id,
             su.id student_id,su.name student_name,su.surname student_surname,
             (CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) student_level,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM slots s
      LEFT JOIN bookings b ON b.id=(
        SELECT b2.id
        FROM booking_slots bs2
        JOIN bookings b2 ON b2.id=bs2.booking_id
        WHERE bs2.slot_id=s.id
          AND b2.status IN ('confirmed','pending_payment','completed','no_show')
        ORDER BY b2.id DESC LIMIT 1
      )
      LEFT JOIN slots base ON base.id=b.slot_id
      LEFT JOIN users su ON su.id=b.student_id
      LEFT JOIN students st ON st.user_id=b.student_id
      WHERE s.lesson_date=?
      ORDER BY s.start_time,s.instructor_id
    """,(today_date,)).fetchall()
    today_slot_lookup={}
    for r in today_slot_rows:
        today_slot_lookup[(r["start_time"],r["instructor_id"])]=dict(r)

    today_multi_rows=con.execute("""
      SELECT s.id slot_id,s.start_time,s.instructor_id,b.id booking_id,b.status booking_status,b.payment_status,b.duration,
             base.lesson_date booking_lesson_date,base.start_time booking_start_time,base.instructor_id booking_instructor_id,
             su.id student_id,su.name student_name,su.surname student_surname,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) student_level,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM slots s
      JOIN booking_slots bs ON bs.slot_id=s.id
      JOIN bookings b ON b.id=bs.booking_id AND b.status IN ('confirmed','pending_payment','completed','no_show')
      LEFT JOIN slots base ON base.id=b.slot_id
      LEFT JOIN users su ON su.id=b.student_id
      LEFT JOIN students st ON st.user_id=b.student_id
      WHERE s.lesson_date=?
      ORDER BY s.start_time,s.instructor_id,b.id
    """,(today_date,)).fetchall()
    today_bookings_by_key={}
    for r in today_multi_rows:
        today_bookings_by_key.setdefault((r["start_time"],r["instructor_id"]),[]).append(dict(r))
    for key,rows in today_bookings_by_key.items():
        if key in today_slot_lookup:
            today_slot_lookup[key]["bookings"]=rows
            today_slot_lookup[key]["shared_count"]=sum(int((r.get("participant_count") or 1)) for r in rows)

    today_bookings=con.execute("""
      SELECT b.id,b.status,b.payment_status,b.duration,b.student_id,s.instructor_id
      FROM bookings b
      JOIN slots s ON s.id=b.slot_id
      WHERE s.lesson_date=?
    """,(today_date,)).fetchall()
    active_today=[r for r in today_bookings if r["status"] in ("confirmed","pending_payment","completed","no_show")]
    active_today_ids=[r["id"] for r in active_today]
    if active_today_ids:
        q=",".join("?" for _ in active_today_ids)
        today_student_count=con.execute(f"SELECT COUNT(DISTINCT student_id) n FROM booking_participants WHERE booking_id IN ({q})",active_today_ids).fetchone()["n"]
    else:
        today_student_count=0
    today_workload_hours=float(con.execute("""
      SELECT COALESCE(SUM(x.duration),0) h
      FROM (
        SELECT DISTINCT s.id,s.duration
        FROM slots s
        JOIN booking_slots bs ON bs.slot_id=s.id
        JOIN bookings b ON b.id=bs.booking_id
        WHERE s.lesson_date=?
          AND b.status IN ('confirmed','pending_payment','completed','no_show')
      ) x
    """,(today_date,)).fetchone()["h"] or 0)
    today_summary={
      "students":today_student_count,
      "lessons":len(active_today),
      "hours":today_workload_hours,
      "completed":sum(1 for r in today_bookings if r["status"]=="completed"),
      "pending":sum(1 for r in today_bookings if r["status"]=="pending_payment" or (r["payment_status"]=="pending" and r["status"] not in ("completed","no_show"))),
      "no_show":sum(1 for r in today_bookings if r["status"]=="no_show"),
      "cancelled":sum(1 for r in today_bookings if str(r["status"] or "").startswith("cancelled")),
    }
    today_activation_states=get_day_activation_state(today_date)
    today_activation_by_column={r["column_no"]:r for r in today_activation_states}
    today_spot=con.execute("""
      SELECT sp.name
      FROM day_spots ds JOIN spots sp ON sp.id=ds.spot_id
      WHERE ds.lesson_date=?
    """,(today_date,)).fetchone()

    # v46 — data used by the Admin Edit/Move Booking modal.  Editing stays
    # inside the booking's existing day, but the Admin may change instructor,
    # start time and duration (1h/2h) as long as the destination is free.
    edit_schedule_data={}
    for edit_date in sorted({date,today_date}):
        edit_instructors=con.execute("""
          SELECT dc.instructor_id,u.name,u.surname
          FROM day_columns dc JOIN users u ON u.id=dc.instructor_id
          WHERE dc.lesson_date=? AND dc.instructor_id IS NOT NULL
          ORDER BY dc.column_no
        """,(edit_date,)).fetchall()
        edit_times=con.execute("""
          SELECT DISTINCT start_time FROM slots
          WHERE lesson_date=? ORDER BY start_time
        """,(edit_date,)).fetchall()
        edit_schedule_data[edit_date]={
          "instructors":[{
            "id":r["instructor_id"],
            "name":((r["name"] or "") + ((" " + r["surname"]) if r["surname"] else ""))
          } for r in edit_instructors],
          "times":[r["start_time"] for r in edit_times]
        }

    # v75.1 visual dashboard: live metrics only, no fake weather/revenue data.
    dashboard_total_students=con.execute("SELECT COUNT(*) n FROM students s JOIN users u ON u.id=s.user_id WHERE COALESCE(u.active,1)=1").fetchone()["n"]
    dashboard_total_instructors=con.execute("SELECT COUNT(*) n FROM instructors i JOIN users u ON u.id=i.user_id WHERE COALESCE(u.active,1)=1").fetchone()["n"]
    dashboard_pending_payments=con.execute("""SELECT COALESCE(SUM(MAX(0,COALESCE(sp.price,0)-COALESCE(sp.paid_amount,0))),0) amount FROM student_packages sp WHERE COALESCE(sp.payment_status,'unpaid')<>'paid'""").fetchone()["amount"]
    dashboard_today_rows=con.execute("""
      SELECT b.id,b.student_id,b.status,b.payment_status,b.duration,s.lesson_date,s.start_time,
             su.name student_name,su.surname student_surname,iu.name instructor_name,iu.surname instructor_surname,
             (SELECT COUNT(*) FROM booking_participants bp WHERE bp.booking_id=b.id) participant_count
      FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN users su ON su.id=b.student_id
      JOIN users iu ON iu.id=s.instructor_id WHERE s.lesson_date=?
      ORDER BY s.start_time,b.id LIMIT 12
    """,(today_date,)).fetchall()
    dashboard_trend=con.execute("""
      SELECT s.lesson_date,COUNT(*) n FROM bookings b JOIN slots s ON s.id=b.slot_id
      WHERE s.lesson_date BETWEEN ? AND ? AND b.status NOT LIKE 'cancelled%'
      GROUP BY s.lesson_date
    """,((datetime.now().date()-timedelta(days=6)).isoformat(),today_date)).fetchall()
    trend_map={r['lesson_date']:int(r['n']) for r in dashboard_trend}
    dashboard_week=[{'day':(datetime.now().date()-timedelta(days=6-i)).strftime('%d/%m'),
                     'count':trend_map.get((datetime.now().date()-timedelta(days=6-i)).isoformat(),0)} for i in range(7)]
    dashboard_week_max=max([x['count'] for x in dashboard_week] or [1]) or 1
    dashboard_recent=con.execute("""
      SELECT b.id,b.status,b.created_at,s.lesson_date,s.start_time,u.name student_name,u.surname student_surname
      FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN users u ON u.id=b.student_id
      ORDER BY b.id DESC LIMIT 6
    """).fetchall()
    dashboard_level_counts={'Beginner':0,'Kiter':0}
    for st in students:
        lvl=st['level'] if isinstance(st,dict) else 'Beginner'
        dashboard_level_counts[lvl]=dashboard_level_counts.get(lvl,0)+1
    con.close()
    slot_lookup={}
    for s in slots:
        slot_lookup[(s["start_time"],s["instructor_id"])]={"slot":s,"booking":booking_by_slot.get(s["id"]),"bookings":bookings_by_slot.get(s["id"],[]),"shared_count":sum(int((r["participant_count"] or 1)) for r in bookings_by_slot.get(s["id"],[]))}
    return render_template(
      "admin.html",slots=slots,bookings=bookings,instructors=instructors,students=students,
      spots=spots,date=date,times=times,timetable=timetable,day_hours=day_hours,
      day_columns=day_columns,slot_lookup=slot_lookup,day_spot=day_spot,week_days=week_days,
      prev_week=prev_week,next_week=next_week,week_start=week_start.isoformat(),week_end=week_end,
      instructor_report=instructor_report,report_week_start=report_week_start.isoformat(),
      report_week_end=report_week_end.isoformat(),activation_states=activation_states,
      activation_by_column=activation_by_column,activation_by_instructor=activation_by_instructor,
      today_date=today_date,today_columns=today_columns,today_hours=today_hours,
      today_slot_lookup=today_slot_lookup,today_summary=today_summary,
      today_activation_states=today_activation_states,
      today_activation_by_column=today_activation_by_column,today_spot=today_spot,
      edit_schedule_data=edit_schedule_data, dashboard_total_students=dashboard_total_students,
      dashboard_total_instructors=dashboard_total_instructors,dashboard_pending_payments=dashboard_pending_payments,
      dashboard_today_rows=dashboard_today_rows,dashboard_week=dashboard_week,dashboard_week_max=dashboard_week_max,
      dashboard_recent=dashboard_recent,dashboard_level_counts=dashboard_level_counts
    )

@app.post("/admin/payment/<int:booking_id>")
def payment_received(booking_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    try:
        # Serialize check-and-update with all other booking writers.
        con.execute("BEGIN IMMEDIATE")
        # A cancelled, completed or no-show booking must never be reopened by payment.
        # Require pending payment and an active booking; the conditional UPDATE also
        # prevents a repeated POST from producing a second audit entry or email.
        updated=con.execute("""
          UPDATE bookings SET payment_status='paid',status='confirmed'
          WHERE id=? AND status IN ('pending_payment','confirmed')
            AND payment_status='pending'
        """,(booking_id,))
        if updated.rowcount != 1:
            con.rollback()
            flash("Η πληρωμή δεν μπορεί να επιβεβαιωθεί: η κράτηση ακυρώθηκε, ολοκληρώθηκε ή δεν εκκρεμεί πληρωμή.")
            return redirect(url_for("admin"))
        con.execute("UPDATE booking_participants SET payment_status='paid' WHERE booking_id=? AND payment_status='pending'",(booking_id,))
        b=con.execute("""
          SELECT b.*,s.lesson_date,s.start_time,sp.name spot,sp.info,sp.map_url
          FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN spots sp ON sp.id=s.spot_id
          WHERE b.id=?
        """,(booking_id,)).fetchone()
        participants=_booking_participants(con,booking_id)
        log_booking_audit(con,booking_id,"payment_received","Επιβεβαιώθηκε η πληρωμή της κράτησης.",u["id"],u["role"],"")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    for person in participants:
        if person["email"]:
            send_email(person["email"],"KiteClub — Η πληρωμή και η κράτησή σου επιβεβαιώθηκαν",
              f"Γεια σου {person['name']},\nΗ κράτησή σου είναι confirmed.\n{b['lesson_date']} {b['start_time']} — {b['spot']}\n{b['info']}\nΧάρτης: {b['map_url']}")
    flash("Η πληρωμή επιβεβαιώθηκε.")
    return redirect(url_for("admin"))

@app.post("/admin/add-slot")
def add_slot():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    con.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id,status) VALUES(?,?,?,?,?)",
      (request.form["date"],request.form["time"],request.form["instructor_id"],request.form["spot_id"],request.form.get("status","open")))
    con.commit(); con.close(); flash("Το slot προστέθηκε."); return redirect(url_for("admin",date=request.form["date"]))


@app.post("/admin/student/add")
def add_student():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    if not password_meets_policy(request.form.get("password", "")):
        flash(password_policy_message())
        return redirect(url_for("admin"))
    first_name=(request.form.get("name") or "").strip()
    surname=(request.form.get("surname") or "").strip()
    if not first_name or not surname:
        flash("Συμπλήρωσε όνομα και επώνυμο.")
        return redirect(url_for("admin"))
    con=db()
    try:
        cur=con.execute("INSERT INTO users(name,surname,email,phone,role,password_hash) VALUES(?,?,?,?,?,?)",(first_name,surname,request.form["email"].strip().lower(),request.form.get("phone","").strip(),"student",generate_password_hash(request.form.get("password") or secrets.token_urlsafe(18))))
        uid=cur.lastrowid; credits=0.0; student_code=_next_student_code(con)
        con.execute("INSERT INTO students(user_id,credits,level,student_code,lesson_type) VALUES(?,?,?,?,?)",(uid,credits,"Beginner",student_code,"private"))
        if credits:
            con.execute("INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",(uid,credits,"manual_adjustment","Initial credits",datetime.now().isoformat()))
        service=(request.form.get("initial_service") or "none").strip(); service_map={"1h":(1.0,60.0),"2h":(2.0,110.0),"8h":(8.0,360.0)}
        if service in service_map:
            hours,price=service_map[service]
            pkg=con.execute("SELECT * FROM packages WHERE COALESCE(package_type,'lesson')='lesson' AND hours=? AND price=? ORDER BY active DESC,id LIMIT 1",(hours,price)).fetchone()
            if pkg:
                now=datetime.now().isoformat(); rule=(pkg["activation_rule"] or "paid_only")
                curp=con.execute("""INSERT INTO student_packages(student_id,package_id,package_name,hours_total,hours_remaining,price,payment_status,purchased_at,paid_at,note,package_type,valid_from,valid_until,activation_rule,paid_amount,credits_activated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(uid,pkg["id"],pkg["name"],hours,0.0,price,"unpaid",now,None,"Αρχική υπηρεσία","lesson",None,None,rule,0.0,0))
                purchase=con.execute("SELECT * FROM student_packages WHERE id=?",(curp.lastrowid,)).fetchone()
                if rule=="immediate": _activate_student_purchase(con,purchase,"Initial service")
        con.commit(); flash("Ο μαθητής δημιουργήθηκε.")
    except sqlite3.IntegrityError:
        con.rollback(); flash("Υπάρχει ήδη χρήστης με αυτό το email.")
    con.close(); return redirect(url_for("admin"))

@app.post("/admin/student/<int:student_id>/credits")
def adjust_credits(student_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    amount=float(request.form.get("amount","0") or 0)
    con=db()
    con.execute("UPDATE students SET credits=credits+? WHERE user_id=?",(amount,student_id))
    con.execute("INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
        (student_id,amount,"manual_adjustment",request.form.get("note","Manual adjustment"),datetime.now().isoformat()))
    con.commit(); con.close(); flash("Τα credits ενημερώθηκαν."); return redirect(url_for("admin"))

@app.post("/admin/instructor/add")
def add_instructor():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    if not password_meets_policy(request.form.get("password", "")):
        flash(password_policy_message())
        return redirect(url_for("admin"))
    con=db()
    try:
        cur=con.execute("INSERT INTO users(name,email,phone,role,password_hash) VALUES(?,?,?,?,?)",
            (request.form["name"].strip(),request.form["email"].strip().lower(),request.form.get("phone","").strip(),"instructor",generate_password_hash(request.form.get("password") or secrets.token_urlsafe(18))))
        uid=cur.lastrowid
        con.execute("INSERT INTO instructors(user_id,hourly_rate,priority,activation_threshold) VALUES(?,?,?,?)",
            (uid,float(request.form.get("hourly_rate","15") or 15),int(request.form.get("priority","1") or 1),float(request.form.get("activation_threshold","5") or 5)))
        con.commit(); flash("Ο εκπαιδευτής δημιουργήθηκε.")
    except sqlite3.IntegrityError:
        con.rollback(); flash("Υπάρχει ήδη χρήστης με αυτό το email.")
    con.close(); return redirect(url_for("admin"))

@app.post("/admin/slot/<int:slot_id>/delete")
def delete_slot(slot_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    active=con.execute("SELECT COUNT(*) n FROM bookings WHERE slot_id=? AND status NOT LIKE 'cancelled%'",(slot_id,)).fetchone()["n"]
    if active: flash("Δεν μπορείς να διαγράψεις slot με ενεργή κράτηση.")
    else:
        con.execute("DELETE FROM slots WHERE id=?",(slot_id,)); con.commit(); flash("Το slot διαγράφηκε.")
    con.close(); return redirect(request.referrer or url_for("admin"))

@app.post("/admin/rebalance")
def manual_rebalance():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    date=request.form.get("date",(datetime.now()+timedelta(days=1)).date().isoformat())
    rebalance_instructors(date); flash("Έγινε επανυπολογισμός εκπαιδευτών.")
    return redirect(url_for("admin",date=date))



@app.post("/admin/slot/<int:slot_id>/status")
def update_slot_status(slot_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    new_status=request.form.get("status","open")
    if new_status not in ("open","standby","closed"):
        new_status="open"
    con=db()
    active=con.execute("""
      SELECT COUNT(*) n FROM bookings
      WHERE slot_id=? AND status NOT LIKE 'cancelled%'
    """,(slot_id,)).fetchone()["n"]
    if active:
        flash("Το slot έχει ενεργή κράτηση και δεν μπορεί να αλλάξει status.")
    else:
        slot_row=con.execute("SELECT lesson_date FROM slots WHERE id=?",(slot_id,)).fetchone()
        override = None if new_status=='standby' else new_status
        con.execute("UPDATE slots SET status=?,manual_override=? WHERE id=?",(new_status,override,slot_id))
        con.commit()
        lesson_date=slot_row["lesson_date"] if slot_row else None
        flash("Το status του slot ενημερώθηκε.")
    con.close()
    if 'lesson_date' in locals() and lesson_date:
        rebalance_instructors(lesson_date)
    return redirect(request.referrer or url_for("admin"))



@app.post("/admin/generate-hours")
def generate_hours():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    try:
        date=parse_gr_date(request.form["date"])
    except ValueError:
        flash("Χρησιμοποίησε ημερομηνία σε μορφή ΗΗ/ΜΜ/ΕΕΕΕ.")
        return redirect(url_for("admin"))
    start=request.form["start_time"]
    end=request.form["end_time"]
    spot_id=int(request.form["spot_id"])

    try:
        start_dt=datetime.strptime(start,"%H:%M")
        end_dt=datetime.strptime(end,"%H:%M")
    except ValueError:
        flash("Μη έγκυρη ώρα.")
        return redirect(url_for("admin",date=date))

    if end_dt <= start_dt:
        flash("Η ώρα λήξης πρέπει να είναι μετά την ώρα έναρξης.")
        return redirect(url_for("admin",date=date))

    con=db()

    # Exactly one spot per day. Changing the spot changes the whole day's schedule.
    previous=con.execute("SELECT spot_id FROM day_spots WHERE lesson_date=?",(date,)).fetchone()
    con.execute("INSERT OR REPLACE INTO day_spots(lesson_date,spot_id) VALUES(?,?)",(date,spot_id))
    if previous and previous["spot_id"] != spot_id:
        con.execute("UPDATE day_hours SET spot_id=? WHERE lesson_date=?",(spot_id,date))
        con.execute("UPDATE slots SET spot_id=? WHERE lesson_date=?",(spot_id,date))

    cur=start_dt
    added=0
    while cur < end_dt:
        t=cur.strftime("%H:%M")
        try:
            con.execute("INSERT INTO day_hours(lesson_date,start_time,spot_id) VALUES(?,?,?)",(date,t,spot_id))
            added+=1
        except sqlite3.IntegrityError:
            pass
        cur += timedelta(hours=1)
    # Create slots for instructors already assigned to the day columns.
    assigned=con.execute("""
      SELECT DISTINCT instructor_id FROM day_columns
      WHERE lesson_date=? AND instructor_id IS NOT NULL
    """,(date,)).fetchall()
    hours=con.execute("SELECT * FROM day_hours WHERE lesson_date=? ORDER BY start_time",(date,)).fetchall()
    for a in assigned:
        for h in hours:
            exists=con.execute("""
              SELECT id,status FROM slots WHERE lesson_date=? AND start_time=? AND instructor_id=?
            """,(date,h["start_time"],a["instructor_id"])).fetchone()
            if not exists:
                con.execute("""
                  INSERT INTO slots(lesson_date,start_time,duration,instructor_id,spot_id,status,manual_override)
                  VALUES(?,?,?,?,?,? ,NULL)
                """,(date,h["start_time"],1,a["instructor_id"],h["spot_id"],"standby"))
    con.commit(); con.close()
    rebalance_instructors(date)
    flash(f"Δημιουργήθηκαν {added} νέες ωριαίες γραμμές.")
    return redirect(url_for("admin",date=date))

@app.post("/admin/hour/<int:hour_id>/assign")
def assign_instructor(hour_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    instructor_id=int(request.form["instructor_id"])
    con=db()
    h=con.execute("SELECT * FROM day_hours WHERE id=?",(hour_id,)).fetchone()
    if not h:
        con.close(); flash("Η ώρα δεν βρέθηκε."); return redirect(url_for("admin"))

    exists=con.execute("""
      SELECT id FROM slots
      WHERE lesson_date=? AND start_time=? AND instructor_id=?
    """,(h["lesson_date"],h["start_time"],instructor_id)).fetchone()

    if exists:
        flash("Ο εκπαιδευτής είναι ήδη τοποθετημένος σε αυτή την ώρα.")
    else:
        con.execute("""
          INSERT INTO slots(lesson_date,start_time,duration,instructor_id,spot_id,status)
          VALUES(?,?,?,?,?,?)
        """,(h["lesson_date"],h["start_time"],1,instructor_id,h["spot_id"],"open"))
        con.commit()
        flash("Ο εκπαιδευτής προστέθηκε στην ώρα.")
    con.close()
    return redirect(url_for("admin",date=h["lesson_date"]))

@app.post("/admin/hour/<int:hour_id>/delete")
def delete_hour(hour_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    h=con.execute("SELECT * FROM day_hours WHERE id=?",(hour_id,)).fetchone()
    if not h:
        con.close(); return redirect(url_for("admin"))
    active=con.execute("""
      SELECT COUNT(*) n
      FROM bookings b JOIN slots s ON s.id=b.slot_id
      WHERE s.lesson_date=? AND s.start_time=? AND b.status NOT LIKE 'cancelled%'
    """,(h["lesson_date"],h["start_time"])).fetchone()["n"]
    if active:
        flash("Δεν μπορείς να διαγράψεις ώρα που έχει ενεργή κράτηση.")
    else:
        con.execute("DELETE FROM slots WHERE lesson_date=? AND start_time=?",(h["lesson_date"],h["start_time"]))
        con.execute("DELETE FROM day_hours WHERE id=?",(hour_id,))
        con.commit()
        flash("Η ώρα αφαιρέθηκε.")
    lesson_date=h["lesson_date"]
    con.close()
    rebalance_instructors(lesson_date)
    return redirect(url_for("admin",date=lesson_date))



@app.post("/admin/day-column/<int:column_no>/assign")
def assign_day_column(column_no):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    date=request.form["date"]
    instructor_raw=request.form.get("instructor_id","").strip()
    instructor_id=int(instructor_raw) if instructor_raw else None

    con=db()

    # Do not allow the same instructor in more than one logical column on the same day.
    if instructor_id:
        duplicate=con.execute("""
          SELECT column_no FROM day_columns
          WHERE lesson_date=? AND instructor_id=? AND column_no<>?
        """,(date,instructor_id,column_no)).fetchone()
        if duplicate:
            con.close()
            flash(f"Ο εκπαιδευτής είναι ήδη επιλεγμένος στο Slot {duplicate['column_no']}.")
            return redirect(url_for("admin",date=date))

    # Read current assignment.
    current=con.execute("SELECT instructor_id FROM day_columns WHERE lesson_date=? AND column_no=?",
                        (date,column_no)).fetchone()
    current_id=current["instructor_id"] if current else None

    # Prevent removing/changing an instructor if there are active bookings in those slots.
    if current_id and current_id != instructor_id:
        active=con.execute("""
          SELECT COUNT(*) n
          FROM bookings b JOIN slots s ON s.id=b.slot_id
          WHERE s.lesson_date=? AND s.instructor_id=? AND b.status NOT LIKE 'cancelled%'
        """,(date,current_id)).fetchone()["n"]
        if active:
            con.close()
            flash("Δεν μπορείς να αλλάξεις αυτόν τον εκπαιδευτή γιατί έχει ενεργές κρατήσεις.")
            return redirect(url_for("admin",date=date))

    con.execute("INSERT OR IGNORE INTO day_columns(lesson_date,column_no,instructor_id) VALUES(?,?,NULL)",
                (date,column_no))
    con.execute("""
      UPDATE day_columns
      SET instructor_id=?,activation_override=NULL,activated_once=0
      WHERE lesson_date=? AND column_no=?
    """,(instructor_id,date,column_no))

    # Remove unbooked slots belonging to the old instructor for this day if no other column uses them.
    if current_id and current_id != instructor_id:
        used_elsewhere=con.execute("""
          SELECT COUNT(*) n FROM day_columns
          WHERE lesson_date=? AND instructor_id=? AND column_no<>?
        """,(date,current_id,column_no)).fetchone()["n"]
        if not used_elsewhere:
            oldslots=con.execute("""
              SELECT s.id FROM slots s
              LEFT JOIN bookings b ON b.slot_id=s.id AND b.status NOT LIKE 'cancelled%'
              WHERE s.lesson_date=? AND s.instructor_id=? AND b.id IS NULL
            """,(date,current_id)).fetchall()
            for r in oldslots:
                con.execute("DELETE FROM slots WHERE id=?",(r["id"],))

    # If an instructor is assigned, create open slots for all generated day hours.
    if instructor_id:
        hours=con.execute("SELECT * FROM day_hours WHERE lesson_date=? ORDER BY start_time",(date,)).fetchall()
        for h in hours:
            exists=con.execute("""
              SELECT id,status FROM slots
              WHERE lesson_date=? AND start_time=? AND instructor_id=?
            """,(date,h["start_time"],instructor_id)).fetchone()
            if not exists:
                con.execute("""
                  INSERT INTO slots(lesson_date,start_time,duration,instructor_id,spot_id,status,manual_override)
                  VALUES(?,?,?,?,?,? ,NULL)
                """,(date,h["start_time"],1,instructor_id,h["spot_id"],"standby"))

    con.commit()
    con.close()
    rebalance_instructors(date)
    flash("Η στήλη ενημερώθηκε.")
    return redirect(url_for("admin",date=date))



@app.post("/admin/day-column/<int:column_no>/activation")
def set_day_column_activation(column_no):
    """Admin override for the daily instructor activation cascade."""
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    date=request.form.get("date","").strip()
    mode=request.form.get("mode","auto").strip().lower()
    if mode not in ("auto","active","standby"):
        mode="auto"

    # Slot 1 defines the base of the cascade and must always stay active.
    if column_no==1 and mode=="standby":
        flash("Το Slot 1 είναι ο βασικός instructor της ημέρας και παραμένει πάντα ACTIVE.")
        return redirect(url_for("admin",date=date))

    con=db()
    row=con.execute("""
      SELECT instructor_id,COALESCE(activated_once,0) activated_once
      FROM day_columns WHERE lesson_date=? AND column_no=?
    """,(date,column_no)).fetchone()
    if not row or not row["instructor_id"]:
        con.close()
        flash("Πρώτα επίλεξε instructor για αυτό το Slot.")
        return redirect(url_for("admin",date=date))

    override=None if mode=="auto" else mode
    con.execute("""
      UPDATE day_columns SET activation_override=?
      WHERE lesson_date=? AND column_no=?
    """,(override,date,column_no))
    con.commit()
    con.close()

    rebalance_instructors(date)
    if mode=="active":
        flash(f"Το Slot {column_no} ενεργοποιήθηκε χειροκίνητα.")
    elif mode=="standby":
        flash(f"Το Slot {column_no} μπήκε χειροκίνητα σε Standby. Οι υπάρχουσες κρατήσεις δεν επηρεάζονται.")
    else:
        flash(f"Το Slot {column_no} επέστρεψε σε αυτόματη λειτουργία.")
    return redirect(url_for("admin",date=date))


@app.post("/admin/slot/<int:slot_id>/manual-state")
def manual_slot_state(slot_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))

    new_status=request.form.get("status","open")
    if new_status not in ("open","standby","closed","pending_payment","booked"):
        new_status="open"

    con=db()
    active=con.execute("""
      SELECT b.id,b.status,b.payment_status
      FROM booking_slots bs
      JOIN bookings b ON b.id=bs.booking_id
      WHERE bs.slot_id=? AND b.status NOT LIKE 'cancelled%'
      LIMIT 1
    """,(slot_id,)).fetchone()

    if active:
        con.close()
        flash("Το slot έχει ενεργή κράτηση και το status του αλλάζει από την κράτηση.")
        return redirect(request.referrer or url_for("admin"))

    slot_row=con.execute("SELECT lesson_date FROM slots WHERE id=?",(slot_id,)).fetchone()
    if new_status == "booked":
        con.close()
        flash("Επίλεξε τον μαθητή για να ολοκληρωθεί η χειροκίνητη κράτηση.")
        return redirect((request.referrer or url_for("admin")) + ("&book_slot=" if "?" in (request.referrer or "") else "?book_slot=") + str(slot_id))
    # Standby means "return this slot to automatic cascade management".
    # Any other Admin choice is a real manual override and must survive
    # the 4-hour activation of the instructor column.
    manual_override = None if new_status == "standby" else new_status
    con.execute("UPDATE slots SET status=?,manual_override=? WHERE id=?",(new_status,manual_override,slot_id))
    con.commit()
    lesson_date=slot_row["lesson_date"] if slot_row else None
    con.close()
    if lesson_date:
        rebalance_instructors(lesson_date)
    flash("Το slot ενημερώθηκε.")
    return redirect(request.referrer or url_for("admin"))



@app.post("/admin/slot/<int:slot_id>/book-student")
def admin_book_student(slot_id):
    """Create a real private/group booking when Admin manually assigns a student to one hour."""
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    try:
        student_id=int(request.form.get("student_id", ""))
    except (TypeError, ValueError):
        flash("Επίλεξε μαθητή από την αναζήτηση.")
        return redirect(request.referrer or url_for("admin"))

    con=db(); con.execute("BEGIN IMMEDIATE")
    slot=con.execute("""
      SELECT s.*,iu.name instructor_name,iu.surname instructor_surname
      FROM slots s JOIN users iu ON iu.id=s.instructor_id
      WHERE s.id=?
    """,(slot_id,)).fetchone()
    student=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,st.credits,st.lesson_type,st.group_id
      FROM students st JOIN users u ON u.id=st.user_id
      WHERE u.id=? AND COALESCE(u.active,1)=1
    """,(student_id,)).fetchone()
    if not slot or not student:
        con.rollback(); con.close(); flash("Το slot ή ο μαθητής δεν βρέθηκε.")
        return redirect(request.referrer or url_for("admin"))

    # v53: Admin may intentionally place up to 3 students in the same instructor/hour
    # (e.g. shared theory). Student self-booking remains exclusive.
    active_bookings=con.execute("""
      SELECT DISTINCT b.id,b.status
      FROM booking_slots bs JOIN bookings b ON b.id=bs.booking_id
      WHERE bs.slot_id=? AND b.status IN ('confirmed','pending_payment','completed','no_show')
    """,(slot_id,)).fetchall()

    if any(ab["status"] in ("completed","no_show") for ab in active_bookings):
        con.rollback(); con.close(); flash("Δεν μπορείς να προσθέσεις μαθητή σε ώρα που έχει ήδη ολοκληρωθεί.")
        return redirect(url_for("admin",date=slot["lesson_date"])+"#day")

    participant_ids=_group_participant_ids(con,student_id)
    expected={"2p":2,"3p":3}.get((student["lesson_type"] or "private").lower(),1)
    if len(participant_ids)!=expected:
        con.rollback(); con.close(); flash("Το group του μαθητή δεν είναι σωστά ρυθμισμένο.")
        return redirect(url_for("admin",date=slot["lesson_date"])+"#day")

    # Count unique people already assigned to this exact slot.
    existing_ids=set()
    for ab in active_bookings:
        for pr in con.execute("SELECT student_id FROM booking_participants WHERE booking_id=?",(ab["id"],)).fetchall():
            existing_ids.add(int(pr["student_id"]))
    new_ids=set(int(x) for x in participant_ids)
    if existing_ids & new_ids:
        con.rollback(); con.close(); flash("Ο μαθητής είναι ήδη καταχωρημένος σε αυτή την ώρα.")
        return redirect(url_for("admin",date=slot["lesson_date"])+"#day")
    if len(existing_ids | new_ids) > 3:
        con.rollback(); con.close(); flash("Μπορούν να υπάρχουν έως 3 μαθητές στην ίδια ώρα.")
        return redirect(url_for("admin",date=slot["lesson_date"])+"#day")

    for sid in participant_ids:
        if _student_time_conflict(con,sid,slot["lesson_date"],slot["start_time"]):
            person=con.execute("SELECT name,surname FROM users WHERE id=?",(sid,)).fetchone()
            pname=(person["name"] or "") + ((" " + person["surname"]) if person and person["surname"] else "")
            con.rollback(); con.close(); flash(f"Ο/Η {pname} έχει ήδη άλλη κράτηση στις {slot['start_time']}.")
            return redirect(url_for("admin",date=slot["lesson_date"])+"#day")
    # Do not reject an instructor conflict caused by another booking on this SAME slot;
    # that is precisely the Admin-only shared-slot feature. Block only a different slot.
    other_instructor_booking=con.execute("""
      SELECT 1
      FROM bookings b
      JOIN booking_slots bs ON bs.booking_id=b.id
      JOIN slots os ON os.id=bs.slot_id
      WHERE os.lesson_date=? AND os.start_time=? AND os.instructor_id=?
        AND os.id<>? AND b.status IN ('confirmed','pending_payment','completed','no_show')
      LIMIT 1
    """,(slot["lesson_date"],slot["start_time"],slot["instructor_id"],slot_id)).fetchone()
    if other_instructor_booking:
        con.rollback(); con.close(); flash("Ο instructor έχει ήδη άλλη κράτηση αυτή την ώρα.")
        return redirect(url_for("admin",date=slot["lesson_date"])+"#day")

    duration=1.0
    cur=con.execute("""
      INSERT INTO bookings(slot_id,student_id,duration,status,payment_status,amount,created_at)
      VALUES(?,?,?,'confirmed','credit',0,?)
    """,(slot_id,student_id,duration,datetime.now().isoformat()))
    booking_id=cur.lastrowid
    status,payment_status,amount=_charge_booking_participants(
        con,booking_id,participant_ids,duration,note_prefix="Admin booking reservation"
    )
    con.execute("UPDATE bookings SET status=?,payment_status=?,amount=? WHERE id=?",
                (status,payment_status,amount,booking_id))
    con.execute("INSERT OR IGNORE INTO booking_slots(booking_id,slot_id) VALUES(?,?)",(booking_id,slot_id))
    con.execute("UPDATE slots SET status='booked',manual_override=NULL WHERE id=?",(slot_id,))
    participants=_booking_participants(con,booking_id)
    log_booking_audit(con,booking_id,"created",f"Κράτηση από Admin για {slot['lesson_date']} {slot['start_time']} ({duration:g}h).",u["id"],u["role"],f"participants={len(participant_ids)}; payment={payment_status}; amount={amount}")
    con.commit(); con.close()

    rebalance_instructors(slot["lesson_date"])
    names=", ".join((r["name"] or "") + ((" " + r["surname"]) if r["surname"] else "") for r in participants)
    if len(participant_ids)>1:
        flash(f"Η group κράτηση καταχωρήθηκε για: {names}." + ("" if status=="confirmed" else " Υπάρχει τουλάχιστον ένα Pending payment."))
    else:
        flash(f"Η κράτηση καταχωρήθηκε για {names}." if status=="confirmed" else f"Η κράτηση για {names} καταχωρήθηκε ως Pending payment.")
    return redirect(url_for("admin",date=slot["lesson_date"])+"#day")



def _admin_booking_action_redirect(lesson_date=None):
    """Return central bookings page when an action started there; otherwise the day timetable."""
    if request.form.get("return_to")=="bookings":
        return redirect(url_for("admin_bookings"))
    if lesson_date:
        return redirect(url_for("admin",date=lesson_date)+"#day")
    return redirect(url_for("admin"))


@app.post("/admin/booking/<int:booking_id>/edit")
def admin_edit_booking(booking_id):
    """Admin can move/edit private or fixed-group bookings without splitting the group."""
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    try:
        student_id=int(request.form.get("student_id", ""))
        instructor_id=int(request.form.get("instructor_id", ""))
        duration=float(request.form.get("duration", "1"))
    except (TypeError, ValueError):
        flash("Έλεγξε μαθητή, instructor και διάρκεια.")
        return _admin_booking_action_redirect()
    if duration not in (1.0,2.0):
        flash("Η διάρκεια μπορεί να είναι 1 ή 2 ώρες.")
        return _admin_booking_action_redirect()

    start_time=(request.form.get("start_time") or "").strip()[:5]
    desired=(request.form.get("booking_state") or "booked").strip().lower()
    if desired not in ("booked","pending"): desired="booked"
    try: datetime.strptime(start_time,"%H:%M")
    except ValueError:
        flash("Η ώρα δεν είναι έγκυρη.")
        return _admin_booking_action_redirect()

    con=db(); con.execute("BEGIN IMMEDIATE")
    b=con.execute("""
      SELECT b.*,s.lesson_date,s.start_time old_start_time,s.instructor_id old_instructor_id
      FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.id=?
    """,(booking_id,)).fetchone()
    if not b:
        con.rollback(); con.close(); flash("Η κράτηση δεν βρέθηκε.")
        return _admin_booking_action_redirect()
    lesson_date=b["lesson_date"]
    if b["status"] not in ("confirmed","pending_payment"):
        con.rollback(); con.close(); flash("Μόνο ενεργές κρατήσεις μπορούν να αλλάξουν. Completed / No-show παραμένουν στο ιστορικό.")
        return _admin_booking_action_redirect(lesson_date)

    student=con.execute("""
      SELECT u.id,u.name,u.surname,st.credits,st.lesson_type,st.group_id
      FROM users u JOIN students st ON st.user_id=u.id
      WHERE u.id=? AND COALESCE(u.active,1)=1
    """,(student_id,)).fetchone()
    if not student:
        con.rollback(); con.close(); flash("Ο μαθητής δεν βρέθηκε.")
        return _admin_booking_action_redirect(lesson_date)
    new_participant_ids=_group_participant_ids(con,student_id)
    expected={"2p":2,"3p":3}.get((student["lesson_type"] or "private").lower(),1)
    if len(new_participant_ids)!=expected:
        con.rollback(); con.close(); flash("Το group του επιλεγμένου μαθητή δεν είναι σωστά ρυθμισμένο.")
        return _admin_booking_action_redirect(lesson_date)

    assigned=con.execute("SELECT 1 FROM day_columns WHERE lesson_date=? AND instructor_id=? LIMIT 1",(lesson_date,instructor_id)).fetchone()
    if not assigned:
        con.rollback(); con.close(); flash("Ο instructor δεν είναι ορισμένος στο πρόγραμμα αυτής της ημέρας.")
        return _admin_booking_action_redirect(lesson_date)

    first=con.execute("SELECT * FROM slots WHERE lesson_date=? AND start_time=? AND instructor_id=? LIMIT 1",
                      (lesson_date,start_time,instructor_id)).fetchone()
    if not first:
        con.rollback(); con.close(); flash("Η νέα ώρα δεν υπάρχει στο πρόγραμμα.")
        return _admin_booking_action_redirect(lesson_date)
    chosen=[first]
    if duration==2.0:
        next_time=(datetime.strptime(start_time,"%H:%M")+timedelta(hours=1)).strftime("%H:%M")
        second=con.execute("SELECT * FROM slots WHERE lesson_date=? AND start_time=? AND instructor_id=? LIMIT 1",
                           (lesson_date,next_time,instructor_id)).fetchone()
        if not second:
            con.rollback(); con.close(); flash("Δεν υπάρχουν δύο συνεχόμενες ώρες στον επιλεγμένο instructor.")
            return _admin_booking_action_redirect(lesson_date)
        chosen.append(second)

    old_links=con.execute("SELECT slot_id FROM booking_slots WHERE booking_id=?",(booking_id,)).fetchall()
    old_slot_ids={r["slot_id"] for r in old_links}; target_ids={r["id"] for r in chosen}
    for target in chosen:
        conflict=con.execute("""
          SELECT b2.id FROM booking_slots bs JOIN bookings b2 ON b2.id=bs.booking_id
          WHERE bs.slot_id=? AND b2.id<>? AND b2.status IN ('confirmed','pending_payment','completed','no_show') LIMIT 1
        """,(target["id"],booking_id)).fetchone()
        if conflict:
            con.rollback(); con.close(); flash("Μία από τις επιλεγμένες ώρες έχει ήδη κράτηση.")
            return _admin_booking_action_redirect(lesson_date)
        if target["id"] not in old_slot_ids and target["status"] in ("closed","pending_payment","booked"):
            con.rollback(); con.close(); flash("Μία από τις επιλεγμένες ώρες είναι κλειστή ή δεσμευμένη χειροκίνητα.")
            return _admin_booking_action_redirect(lesson_date)
        for sid in new_participant_ids:
            if _student_time_conflict(con,sid,lesson_date,target["start_time"],exclude_booking_id=booking_id):
                person=con.execute("SELECT name,surname FROM users WHERE id=?",(sid,)).fetchone()
                pname=(person["name"] or "") + ((" " + person["surname"]) if person and person["surname"] else "")
                con.rollback(); con.close(); flash(f"Ο/Η {pname} έχει ήδη άλλη κράτηση στις {target['start_time']}.")
                return _admin_booking_action_redirect(lesson_date)
        if _instructor_time_conflict(con,instructor_id,lesson_date,target["start_time"],exclude_booking_id=booking_id):
            con.rollback(); con.close(); flash(f"Ο instructor έχει ήδη άλλο μάθημα στις {target['start_time']}.")
            return _admin_booking_action_redirect(lesson_date)

    old_participants=_booking_participants(con,booking_id)
    old_participant_ids=[r["student_id"] for r in old_participants] or [b["student_id"]]
    old_duration=float(b["duration"] or 1)
    same_people=set(old_participant_ids)==set(new_participant_ids)
    same_payment_state=((desired=="booked" and b["status"]=="confirmed") or (desired=="pending" and b["status"]=="pending_payment"))
    preserve_payment=same_people and old_duration==duration and same_payment_state

    if preserve_payment:
        new_status=b["status"]; new_payment=b["payment_status"]; new_amount=float(b["amount"] or 0)
    else:
        _refund_booking_participants(con,booking_id,"admin_booking_edit_refund","Credit returned before editing booking")
        con.execute("DELETE FROM booking_participants WHERE booking_id=?",(booking_id,))
        force_pending=(desired=="pending") or (b["payment_status"]=="paid" and (not same_people or old_duration!=duration))
        new_status,new_payment,new_amount=_charge_booking_participants(
            con,booking_id,new_participant_ids,duration,force_pending=force_pending,
            note_prefix="Credit reserved after editing booking"
        )
        if desired=="pending":
            new_status="pending_payment"; new_payment="pending"

    for sid in old_slot_ids-target_ids:
        con.execute("UPDATE slots SET status='open' WHERE id=?",(sid,))
    con.execute("DELETE FROM booking_slots WHERE booking_id=?",(booking_id,))
    for target in chosen:
        con.execute("INSERT INTO booking_slots(booking_id,slot_id) VALUES(?,?)",(booking_id,target["id"]))
        con.execute("UPDATE slots SET status='booked',manual_override=NULL WHERE id=?",(target["id"],))

    con.execute("""
      UPDATE bookings SET slot_id=?,student_id=?,duration=?,status=?,payment_status=?,amount=? WHERE id=?
    """,(first["id"],student_id,duration,new_status,new_payment,new_amount,booking_id))
    participants=_booking_participants(con,booking_id)
    log_booking_audit(con,booking_id,"edited",f"Ο Admin ενημέρωσε την κράτηση σε {start_time} ({duration:g}h).",u["id"],u["role"],f"student_id={student_id}; instructor_id={instructor_id}; status={new_status}; payment={new_payment}")
    con.commit(); con.close()
    rebalance_instructors(lesson_date)

    names=", ".join((r["name"] or "") + ((" " + r["surname"]) if r["surname"] else "") for r in participants)
    if new_status=="pending_payment" and desired=="booked":
        flash(f"Η κράτηση ενημερώθηκε για {names}, αλλά υπάρχει Pending payment επειδή δεν υπάρχουν αρκετές ώρες σε όλα τα μέλη.")
    else:
        flash(f"Η κράτηση ενημερώθηκε για {names}: {start_time}, {duration:g}h.")
    return _admin_booking_action_redirect(lesson_date)


@app.post("/admin/booking/<int:booking_id>/cancel")
def admin_cancel_booking(booking_id):
    """Admin cancellation has no 6-hour restriction and refunds charged participants."""
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    con=db(); con.execute("BEGIN IMMEDIATE")
    b=con.execute("""
      SELECT b.*,s.lesson_date FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.id=?
    """,(booking_id,)).fetchone()
    if not b:
        con.rollback(); con.close(); flash("Η κράτηση δεν βρέθηκε.")
        return _admin_booking_action_redirect()
    lesson_date=b["lesson_date"]
    if b["status"] not in ("confirmed","pending_payment"):
        con.rollback(); con.close(); flash("Η κράτηση δεν είναι πλέον ενεργή.")
        return _admin_booking_action_redirect(lesson_date)

    participant_count=con.execute("SELECT COUNT(*) n FROM booking_participants WHERE booking_id=?",(booking_id,)).fetchone()["n"]
    refunded=_refund_booking_participants(con,booking_id,"admin_booking_cancel_refund","Admin cancellation refund")
    linked=con.execute("SELECT slot_id FROM booking_slots WHERE booking_id=?",(booking_id,)).fetchall()
    con.execute("UPDATE bookings SET status='cancelled_admin' WHERE id=?",(booking_id,))
    for r in linked:
        con.execute("UPDATE slots SET status='open' WHERE id=?",(r["slot_id"],))
    log_booking_audit(con,booking_id,"cancelled","Ακύρωση κράτησης από Admin.",u["id"],u["role"],f"refunded_hours={refunded}; participants={participant_count}")
    con.commit(); con.close()
    rebalance_instructors(lesson_date)

    label="group κράτηση" if participant_count>1 else "κράτηση"
    flash(f"Η {label} ακυρώθηκε από τον Admin" + (" και επιστράφηκαν οι χρεωμένες ώρες." if refunded else "."))
    return _admin_booking_action_redirect(lesson_date)


@app.post("/admin/day-spot")
def update_day_spot():
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    try:
        date=parse_gr_date(request.form["date"])
        spot_id=int(request.form["spot_id"])
    except (ValueError, KeyError):
        flash("Μη έγκυρη ημερομηνία ή spot.")
        return redirect(url_for("admin"))

    con=db()
    con.execute("INSERT OR REPLACE INTO day_spots(lesson_date,spot_id) VALUES(?,?)",(date,spot_id))
    con.execute("UPDATE day_hours SET spot_id=? WHERE lesson_date=?",(spot_id,date))
    con.execute("UPDATE slots SET spot_id=? WHERE lesson_date=?",(spot_id,date))
    con.commit()
    con.close()
    flash("Το spot της ημέρας ενημερώθηκε.")
    return redirect(url_for("admin",date=date))



@app.post("/admin/instructors/add")
def admin_add_instructor():
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    name=request.form.get("name","").strip()
    email=request.form.get("email","").strip().lower()
    phone=request.form.get("phone","").strip()
    password=request.form.get("password","").strip()
    hourly_rate=request.form.get("hourly_rate","15").strip()
    threshold=request.form.get("activation_threshold","4").strip()

    if not name or not email or not password:
        flash("Συμπλήρωσε όνομα, email και password.")
        return redirect(url_for("admin")+"#instructors")
    if not password_meets_policy(password):
        flash(password_policy_message())
        return redirect(url_for("admin")+"#instructors")

    try:
        hourly_rate=float(hourly_rate or 0)
        threshold=float(threshold or 0)
    except ValueError:
        flash("Η ωριαία αμοιβή και το threshold πρέπει να είναι αριθμοί.")
        return redirect(url_for("admin")+"#instructors")

    con=db()
    exists=con.execute("SELECT id FROM users WHERE lower(email)=lower(?)",(email,)).fetchone()
    if exists:
        con.close()
        flash("Υπάρχει ήδη χρήστης με αυτό το email.")
        return redirect(url_for("admin")+"#instructors")

    # New instructors are added with the lowest priority after existing instructors.
    max_priority=con.execute("SELECT COALESCE(MAX(priority),0) p FROM instructors").fetchone()["p"]
    cur=con.execute("""
      INSERT INTO users(name,email,phone,role,password_hash)
      VALUES(?,?,?,?,?)
    """,(name,email,phone,"instructor",generate_password_hash(password)))
    user_id=cur.lastrowid

    con.execute("""
      INSERT INTO instructors(user_id,priority,activation_threshold,hourly_rate)
      VALUES(?,?,?,?)
    """,(user_id,int(max_priority)+1,threshold,hourly_rate))

    con.commit()
    con.close()
    flash(f"Ο instructor {name} προστέθηκε.")
    return redirect(url_for("admin")+"#instructors")


@app.post("/admin/instructors/<int:instructor_id>/delete")
def admin_delete_instructor(instructor_id):
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    con=db()
    inst=con.execute("""
      SELECT u.id,u.name
      FROM users u JOIN instructors i ON i.user_id=u.id
      WHERE u.id=?
    """,(instructor_id,)).fetchone()

    if not inst:
        con.close()
        flash("Ο instructor δεν βρέθηκε.")
        return redirect(url_for("admin")+"#instructors")

    today=datetime.now().date().isoformat()

    future_booking=con.execute("""
      SELECT COUNT(*) n
      FROM bookings b
      JOIN slots s ON s.id=b.slot_id
      WHERE s.instructor_id=?
        AND s.lesson_date>=?
        AND b.status IN ('confirmed','pending_payment')
    """,(instructor_id,today)).fetchone()["n"]

    if future_booking:
        con.close()
        flash("Δεν μπορεί να διαγραφεί: έχει μελλοντικά μαθήματα/κρατήσεις.")
        return redirect(url_for("admin")+"#instructors")

    # Clear day-column assignments so old schedules do not reference the removed instructor.
    con.execute("UPDATE day_columns SET instructor_id=NULL WHERE instructor_id=?",(instructor_id,))

    # Keep historical completed bookings and instructor_hours intact by keeping the user
    # if they are referenced historically. Instead deactivate login and remove from instructors.
    historical=con.execute("""
      SELECT
        (SELECT COUNT(*) FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE s.instructor_id=?) +
        (SELECT COUNT(*) FROM instructor_hours WHERE instructor_id=?) AS n
    """,(instructor_id,instructor_id)).fetchone()["n"]

    con.execute("DELETE FROM instructors WHERE user_id=?",(instructor_id,))

    if historical:
        # Preserve historical names/data, but remove instructor access.
        con.execute("""
          UPDATE users
          SET role='inactive_instructor', email='inactive_'||id||'_'||email
          WHERE id=?
        """,(instructor_id,))
    else:
        # No historical references: safe to remove associated unused slots then user.
        con.execute("""
          DELETE FROM slots
          WHERE instructor_id=?
            AND id NOT IN (SELECT slot_id FROM booking_slots)
        """,(instructor_id,))
        con.execute("DELETE FROM users WHERE id=?",(instructor_id,))

    con.commit()
    con.close()
    flash(f"Ο instructor {inst['name']} αφαιρέθηκε.")
    return redirect(url_for("admin")+"#instructors")




@app.route("/admin/instructors/<int:instructor_id>", methods=["GET","POST"])
def admin_instructor_profile(instructor_id):
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    con=db()
    inst=con.execute("""
      SELECT u.id,u.name,u.surname,u.instagram,u.email,u.phone,u.profile_photo,
             i.hourly_rate,i.activation_threshold,i.priority
      FROM users u JOIN instructors i ON i.user_id=u.id
      WHERE u.id=?
    """,(instructor_id,)).fetchone()

    if not inst:
        con.close()
        flash("Ο instructor δεν βρέθηκε.")
        return redirect(url_for("admin")+"#instructors")

    if request.method=="POST":
        name=request.form.get("name","").strip()
        surname=request.form.get("surname","").strip()
        instagram=request.form.get("instagram","").strip()
        email=request.form.get("email","").strip().lower()
        phone=request.form.get("phone","").strip()
        password=request.form.get("password","").strip()
        hourly_rate=request.form.get("hourly_rate","15").strip()
        threshold=request.form.get("activation_threshold","4").strip()

        if not name or not email:
            con.close(); flash("Όνομα και email είναι υποχρεωτικά.")
            return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))
        try:
            hourly_rate=float(hourly_rate); threshold=float(threshold)
        except ValueError:
            con.close(); flash("Μη έγκυρη αμοιβή ή threshold.")
            return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))
        duplicate=con.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND id<>?",(email,instructor_id)).fetchone()
        if duplicate:
            con.close(); flash("Το email χρησιμοποιείται ήδη.")
            return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))
        photo=inst["profile_photo"]
        try:
            new_photo=save_profile_photo(request.files.get("profile_photo"),instructor_id)
            if new_photo: photo=new_photo
        except ValueError as e:
            con.close(); flash(str(e))
            return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))
        con.execute("UPDATE users SET name=?,surname=?,instagram=?,email=?,phone=?,profile_photo=? WHERE id=?",
                    (name,surname,instagram,email,phone,photo,instructor_id))
        if password:
            if not password_meets_policy(password):
                con.close()
                flash(password_policy_message())
                return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))
            con.execute("UPDATE users SET password_hash=? WHERE id=?",(generate_password_hash(password),instructor_id))
        con.execute("UPDATE instructors SET hourly_rate=?,activation_threshold=? WHERE user_id=?",
                    (hourly_rate,threshold,instructor_id))
        con.commit(); con.close(); flash("Το προφίλ instructor ενημερώθηκε.")
        return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))

    today_dt=datetime.now().date()
    default_from=today_dt.replace(day=1)
    raw_from=request.args.get("from","").strip()
    raw_to=request.args.get("to","").strip()
    try: period_from=datetime.strptime(raw_from,"%Y-%m-%d").date() if raw_from else default_from
    except ValueError: period_from=default_from
    try: period_to=datetime.strptime(raw_to,"%Y-%m-%d").date() if raw_to else today_dt
    except ValueError: period_to=today_dt
    if period_from>period_to: period_from,period_to=period_to,period_from
    pfrom=period_from.isoformat(); pto=period_to.isoformat()

    completed_hours=float(con.execute("""
      SELECT COALESCE(SUM(hours),0) h FROM instructor_hours
      WHERE instructor_id=? AND lesson_date BETWEEN ? AND ?
    """,(instructor_id,pfrom,pto)).fetchone()["h"] or 0)
    completed_lessons=int(con.execute("""
      SELECT COUNT(DISTINCT booking_id) n FROM instructor_hours
      WHERE instructor_id=? AND lesson_date BETWEEN ? AND ?
    """,(instructor_id,pfrom,pto)).fetchone()["n"] or 0)

    booking_report=con.execute("""
      SELECT b.id,b.status,b.duration,b.next_skill,sl.lesson_date,sl.start_time,sl.id slot_id,
             su.name student,su.surname student_surname,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) AS level,
             COALESCE(day_sp.name,slot_sp.name) spot,
             (SELECT COUNT(*) FROM booking_participants bp WHERE bp.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp2 JOIN users pu ON pu.id=bp2.student_id
               WHERE bp2.booking_id=b.id) participant_names
      FROM bookings b JOIN slots sl ON sl.id=b.slot_id
      JOIN users su ON su.id=b.student_id LEFT JOIN students st ON st.user_id=su.id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE sl.instructor_id=? AND b.status NOT LIKE 'cancelled%' AND sl.lesson_date BETWEEN ? AND ?
      ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(instructor_id,pfrom,pto)).fetchall()

    completed_report=[r for r in booking_report if r["status"]=="completed"]
    no_show_report=[r for r in booking_report if r["status"]=="no_show"]

    # Group hours: count instructor workload once per occupied slot, even with multiple participants.
    group_hours=float(con.execute("""
      SELECT COALESCE(SUM(x.duration),0) h FROM (
        SELECT sl.id, MAX(COALESCE(b.duration,1)) duration
        FROM slots sl JOIN bookings b ON b.slot_id=sl.id
        WHERE sl.instructor_id=? AND sl.lesson_date BETWEEN ? AND ?
          AND b.status='completed'
          AND (SELECT COUNT(*) FROM booking_participants bp WHERE bp.booking_id=b.id)>1
        GROUP BY sl.id
      ) x
    """,(instructor_id,pfrom,pto)).fetchone()["h"] or 0)
    no_show_hours=float(con.execute("""
      SELECT COALESCE(SUM(x.duration),0) h FROM (
        SELECT sl.id, MAX(COALESCE(b.duration,1)) duration
        FROM slots sl JOIN bookings b ON b.slot_id=sl.id
        WHERE sl.instructor_id=? AND sl.lesson_date BETWEEN ? AND ? AND b.status='no_show'
        GROUP BY sl.id
      ) x
    """,(instructor_id,pfrom,pto)).fetchone()["h"] or 0)

    payments=con.execute("SELECT * FROM instructor_payments WHERE instructor_id=? ORDER BY payment_date DESC,id DESC",(instructor_id,)).fetchall()
    period_payments=[r for r in payments if pfrom <= str(r["payment_date"])[:10] <= pto]
    total_earned=completed_hours*float(inst["hourly_rate"] or 0)
    total_paid=float(sum(float(r["amount"] or 0) for r in period_payments))
    balance=total_earned-total_paid

    # Weekly completed-hour buckets inside selected period.
    hour_rows=con.execute("""
      SELECT lesson_date,COALESCE(SUM(hours),0) hours FROM instructor_hours
      WHERE instructor_id=? AND lesson_date BETWEEN ? AND ?
      GROUP BY lesson_date ORDER BY lesson_date
    """,(instructor_id,pfrom,pto)).fetchall()
    buckets={}
    for r in hour_rows:
        try: d=datetime.strptime(r["lesson_date"],"%Y-%m-%d").date()
        except Exception: continue
        monday=d-timedelta(days=d.weekday())
        buckets[monday]=buckets.get(monday,0.0)+float(r["hours"] or 0)
    weekly_hours=[]
    for monday,h in sorted(buckets.items()):
        sunday=monday+timedelta(days=6)
        weekly_hours.append({"label":f"{monday.strftime('%d/%m')}–{sunday.strftime('%d/%m')}","hours":round(h,1)})
    if not weekly_hours:
        weekly_hours=[{"label":"—","hours":0.0}]
    max_week=max([r["hours"] for r in weekly_hours] or [1]) or 1
    for r in weekly_hours: r["pct"]=round((r["hours"]/max_week)*100,1) if max_week else 0

    private_hours=max(0.0,completed_hours-group_hours)
    distribution=[
      {"label":"Private","hours":round(private_hours,1)},
      {"label":"Group","hours":round(group_hours,1)},
      {"label":"No-show","hours":round(no_show_hours,1)},
    ]

    con.close()
    return render_template(
      "admin_instructor_profile.html", instructor=inst,
      completed_hours=completed_hours, completed_lessons=completed_lessons,
      booking_report=booking_report, completed_report=completed_report, no_show_report=no_show_report,
      payments=payments, period_payments=period_payments,
      total_earned=total_earned,total_paid=total_paid,balance=balance,
      group_hours=group_hours,no_show_hours=no_show_hours,private_hours=private_hours,
      weekly_hours=weekly_hours,distribution=distribution,
      period_from=pfrom,period_to=pto,today=today_dt.isoformat()
    )


@app.post("/admin/instructors/<int:instructor_id>/payments/add")
def admin_add_instructor_payment(instructor_id):
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    try:
        amount=float(request.form.get("amount","0") or 0)
    except ValueError:
        amount=0
    payment_date=request.form.get("payment_date","").strip() or datetime.now().date().isoformat()
    note=request.form.get("note","").strip()

    if amount<=0:
        flash("Το ποσό πληρωμής πρέπει να είναι μεγαλύτερο από 0.")
        return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))

    try:
        datetime.strptime(payment_date,"%Y-%m-%d")
    except ValueError:
        flash("Μη έγκυρη ημερομηνία πληρωμής.")
        return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))

    con=db()
    exists=con.execute("SELECT user_id FROM instructors WHERE user_id=?",(instructor_id,)).fetchone()
    if not exists:
        con.close()
        flash("Ο instructor δεν βρέθηκε.")
        return redirect(url_for("admin")+"#instructors")

    con.execute("""
      INSERT INTO instructor_payments(instructor_id,amount,payment_date,note,created_at)
      VALUES(?,?,?,?,?)
    """,(instructor_id,amount,payment_date,note,datetime.now().isoformat()))
    con.commit(); con.close()
    flash("Η πληρωμή καταχωρήθηκε.")
    return redirect(url_for("admin_instructor_profile",instructor_id=instructor_id))


@app.route("/admin/students/<int:student_id>", methods=["GET","POST"])
def admin_student_profile(student_id):
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    con=db()
    st=con.execute("""
      SELECT u.id,u.name,u.surname,u.instagram,u.email,u.phone,u.profile_photo,
             s.level,s.credits,s.student_code,s.lesson_type,s.group_id,
             COALESCE(s.crew_member,0) crew_member,s.crew_start_date,s.crew_end_date,COALESCE(s.crew_fee,0) crew_fee
      FROM users u JOIN students s ON s.user_id=u.id
      WHERE u.id=?
    """,(student_id,)).fetchone()

    if not st:
        con.close()
        flash("Ο μαθητής δεν βρέθηκε.")
        return redirect(url_for("admin")+"#students")

    if request.method=="POST":
        name=request.form.get("name","").strip()
        surname=request.form.get("surname","").strip()
        instagram=request.form.get("instagram","").strip()
        email=request.form.get("email","").strip().lower()
        phone=request.form.get("phone","").strip()
        level=(st["level"] or "Beginner").strip()
        password=request.form.get("password","").strip()
        lesson_type=request.form.get("lesson_type","private").strip().lower()
        partner_ids=request.form.getlist("group_member_id")
        crew_member=1 if request.form.get("crew_member")=="1" else 0
        crew_start_date=request.form.get("crew_start_date","").strip() or None
        crew_end_date=request.form.get("crew_end_date","").strip() or None
        try:
            crew_fee=float(request.form.get("crew_fee","0") or 0)
        except (TypeError,ValueError):
            crew_fee=0.0
        if crew_fee < 0:
            crew_fee=0.0
        if crew_member and crew_start_date and crew_end_date and crew_end_date < crew_start_date:
            con.close()
            flash("Η ημερομηνία λήξης Crew Member δεν μπορεί να είναι πριν από την έναρξη.")
            return redirect(url_for("admin_student_profile",student_id=student_id))

        if not name or not email:
            con.close()
            flash("Όνομα και email είναι υποχρεωτικά.")
            return redirect(url_for("admin_student_profile",student_id=student_id))

        duplicate=con.execute("""
          SELECT id FROM users WHERE lower(email)=lower(?) AND id<>?
        """,(email,student_id)).fetchone()
        if duplicate:
            con.close()
            flash("Το email χρησιμοποιείται ήδη.")
            return redirect(url_for("admin_student_profile",student_id=student_id))

        photo=st["profile_photo"]
        try:
            new_photo=save_profile_photo(request.files.get("profile_photo"),student_id)
            if new_photo:
                photo=new_photo
        except ValueError as e:
            con.close()
            flash(str(e))
            return redirect(url_for("admin_student_profile",student_id=student_id))

        con.execute("""
          UPDATE users
          SET name=?,surname=?,instagram=?,email=?,phone=?,profile_photo=?
          WHERE id=?
        """,(name,surname,instagram,email,phone,photo,student_id))

        if password:
            if not password_meets_policy(password):
                con.close()
                flash(password_policy_message())
                return redirect(url_for("admin_student_profile",student_id=student_id))
            con.execute("""
              UPDATE users SET password_hash=? WHERE id=?
            """,(generate_password_hash(password),student_id))

        con.execute("""
          UPDATE students
          SET level=?,crew_member=?,crew_start_date=?,crew_end_date=?,crew_fee=?
          WHERE user_id=?
        """,(level,crew_member,crew_start_date,crew_end_date,crew_fee,student_id))
        try:
            _set_student_group(con,student_id,lesson_type,partner_ids)
        except ValueError as e:
            con.rollback(); con.close()
            flash(str(e))
            return redirect(url_for("admin_student_profile",student_id=student_id))

        con.commit()
        con.close()
        flash("Το προφίλ μαθητή ενημερώθηκε.")
        return redirect(url_for("admin_student_profile",student_id=student_id))

    booking_report=con.execute("""
      SELECT b.id,COALESCE(bp.attendance_status,b.status) status,bp.payment_status,bp.amount,b.duration,
             COALESCE(bp.participant_next_skill,b.next_skill) next_skill,
             COALESCE(bp.participant_notes,b.instructor_notes) instructor_notes,
             sl.lesson_date,sl.start_time,
             ins.name instructor,ins.surname instructor_surname,
             COALESCE(day_sp.name,slot_sp.name) spot
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users ins ON ins.id=sl.instructor_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE bp.student_id=?
      ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(student_id,)).fetchall()

    completed_report=con.execute("""
      SELECT b.id,b.duration,COALESCE(bp.participant_next_skill,b.next_skill) next_skill,
             COALESCE(bp.attendance_at,b.completed_at) completed_at,
             sl.lesson_date,sl.start_time,
             ins.name instructor,ins.surname instructor_surname,
             COALESCE(day_sp.name,slot_sp.name) spot
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users ins ON ins.id=sl.instructor_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE bp.student_id=? AND COALESCE(bp.attendance_status,b.status)='completed'
      ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(student_id,)).fetchall()

    no_show_report=con.execute("""
      SELECT b.id,b.duration,COALESCE(bp.attendance_at,b.no_show_at) no_show_at,
             sl.lesson_date,sl.start_time,
             ins.name instructor,ins.surname instructor_surname,
             COALESCE(day_sp.name,slot_sp.name) spot
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users ins ON ins.id=sl.instructor_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE bp.student_id=? AND COALESCE(bp.attendance_status,b.status)='no_show'
      ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(student_id,)).fetchall()

    makeup_report=con.execute("""
      SELECT b.id,b.duration,COALESCE(bp.attendance_at,b.completed_at,b.no_show_at) attendance_at,
             COALESCE(bp.participant_notes,b.instructor_notes) instructor_notes,
             sl.lesson_date,sl.start_time,
             ins.name instructor,ins.surname instructor_surname,
             COALESCE(day_sp.name,slot_sp.name) spot
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users ins ON ins.id=sl.instructor_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE bp.student_id=? AND bp.attendance_status='makeup'
      ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(student_id,)).fetchall()

    credit_history=con.execute("""
      SELECT *
      FROM credit_ledger
      WHERE student_id=?
      ORDER BY created_at DESC,id DESC
    """,(student_id,)).fetchall()

    total_booked_hours=float(sum(
      float(r["duration"] or 0)
      for r in booking_report
      if not str(r["status"]).startswith("cancelled")
    ))
    completed_hours=float(sum(float(r["duration"] or 0) for r in completed_report))
    no_show_hours=float(sum(float(r["duration"] or 0) for r in no_show_report))
    no_show_count=len(no_show_report)
    makeup_hours=float(sum(float(r["duration"] or 0) for r in makeup_report))
    makeup_count=len(makeup_report)
    total_credit_in=float(sum(float(r["amount"] or 0) for r in credit_history if float(r["amount"] or 0)>0))
    total_credit_out=abs(float(sum(float(r["amount"] or 0) for r in credit_history if float(r["amount"] or 0)<0)))

    available_packages=con.execute("""
      SELECT * FROM packages WHERE active=1 ORDER BY hours,price,id
    """).fetchall()
    package_history=con.execute("""
      SELECT sp.*,p.name catalog_name
      FROM student_packages sp
      LEFT JOIN packages p ON p.id=sp.package_id
      WHERE sp.student_id=?
      ORDER BY sp.purchased_at DESC,sp.id DESC
    """,(student_id,)).fetchall()
    package_payments=con.execute("SELECT * FROM student_payments WHERE student_id=? ORDER BY payment_date DESC,id DESC",(student_id,)).fetchall()
    group_members=_group_members(con,student_id)
    group_partner_ids=[r["id"] for r in group_members if r["id"]!=student_id]
    all_students=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,s.student_code,s.lesson_type,s.group_id
      FROM users u JOIN students s ON s.user_id=u.id
      WHERE u.id<>? AND COALESCE(u.active,1)=1
        AND (s.group_id IS NULL OR s.group_id=?)
      ORDER BY u.name,u.surname
    """,(student_id,st["group_id"])).fetchall()

    student_photos=con.execute("""
      SELECT * FROM student_photos WHERE student_id=?
      ORDER BY COALESCE(photo_date,'') DESC, created_at DESC, id DESC
    """,(student_id,)).fetchall()
    progress=get_student_progress(con,student_id)

    today_iso=datetime.now().date().isoformat()
    crew_status="inactive"
    if int(st["crew_member"] or 0)==1:
        if st["crew_end_date"] and st["crew_end_date"] < today_iso:
            crew_status="expired"
        elif st["crew_start_date"] and st["crew_start_date"] > today_iso:
            crew_status="scheduled"
        else:
            crew_status="active"

    con.close()
    return render_template(
      "admin_student_profile.html",
      student=st,
      booking_report=booking_report,
      completed_report=completed_report,
      no_show_report=no_show_report,makeup_report=makeup_report,
      credit_history=credit_history,
      total_booked_hours=total_booked_hours,
      completed_hours=completed_hours,
      no_show_hours=no_show_hours,
      no_show_count=no_show_count,makeup_hours=makeup_hours,makeup_count=makeup_count,
      total_credit_in=total_credit_in,
      total_credit_out=total_credit_out,
      available_packages=available_packages,
      package_history=package_history,
      package_payments=package_payments,
      group_members=group_members,
      group_partner_ids=group_partner_ids,
      all_students=all_students,
      crew_status=crew_status,
      student_photos=student_photos,
      progress=progress
    )


@app.post("/admin/students/<int:student_id>/progress")
def admin_student_progress(student_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    exists=con.execute("SELECT 1 FROM students WHERE user_id=?",(student_id,)).fetchone()
    if not exists:
        con.close(); flash("Ο μαθητής δεν βρέθηκε."); return redirect(url_for("admin")+"#students")
    try:
        before,after,progress=set_student_skill_progress(con,student_id,request.form.get("skill_key",""),request.form.get("status",""),u["id"])
        con.commit()
        if before!=after and after=="Kiter": flash("Ο μαθητής ολοκλήρωσε και τα 4 Levels και έγινε Kiter.")
        else: flash("Η πρόοδος ενημερώθηκε.")
    except ValueError as e:
        con.rollback(); flash(str(e))
    finally:
        con.close()
    return redirect(url_for("admin_student_profile",student_id=student_id)+"#progress")


@app.post("/admin/students/<int:student_id>/photos")
def admin_student_photo_upload(student_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    exists=con.execute("SELECT 1 FROM students WHERE user_id=?",(student_id,)).fetchone()
    if not exists:
        con.close(); flash("Ο μαθητής δεν βρέθηκε."); return redirect(url_for("admin")+"#students")
    files=request.files.getlist("photos")
    caption=request.form.get("caption","").strip()
    photo_date=request.form.get("photo_date","").strip() or datetime.now().date().isoformat()
    saved=0
    try:
        for f in files:
            path=save_student_gallery_photo(f,student_id)
            if path:
                con.execute("INSERT INTO student_photos(student_id,file_path,caption,photo_date,created_at) VALUES(?,?,?,?,?)",
                            (student_id,path,caption,photo_date,datetime.now().isoformat()))
                saved+=1
        con.commit()
    except ValueError as e:
        con.rollback(); con.close(); flash(str(e)); return redirect(url_for("admin_student_profile",student_id=student_id)+"#photos")
    con.close()
    flash(f"Ανέβηκαν {saved} φωτογραφίες." if saved!=1 else "Η φωτογραφία ανέβηκε.")
    return redirect(url_for("admin_student_profile",student_id=student_id)+"#photos")

@app.post("/admin/students/<int:student_id>/photos/<int:photo_id>/delete")
def admin_student_photo_delete(student_id,photo_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db()
    row=con.execute("SELECT * FROM student_photos WHERE id=? AND student_id=?",(photo_id,student_id)).fetchone()
    if row:
        con.execute("DELETE FROM student_photos WHERE id=?",(photo_id,))
        con.commit()
        try:
            fp=UPLOAD_ROOT/str(row["file_path"]).replace("uploads/", "", 1)
            if fp.exists(): fp.unlink()
        except Exception:
            pass
        flash("Η φωτογραφία διαγράφηκε.")
    else:
        flash("Η φωτογραφία δεν βρέθηκε.")
    con.close()
    return redirect(url_for("admin_student_profile",student_id=student_id)+"#photos")

@app.post("/admin/students/<int:student_id>/credits/add")
def admin_student_profile_credit_adjustment(student_id):
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    try:
        amount=float(request.form.get("amount","0") or 0)
    except ValueError:
        amount=0

    note=request.form.get("note","").strip() or "Manual adjustment"

    if amount==0:
        flash("Η μεταβολή credits δεν μπορεί να είναι 0.")
        return redirect(url_for("admin_student_profile",student_id=student_id))

    con=db()
    exists=con.execute("SELECT user_id FROM students WHERE user_id=?",(student_id,)).fetchone()
    if not exists:
        con.close()
        flash("Ο μαθητής δεν βρέθηκε.")
        return redirect(url_for("admin")+"#students")

    con.execute("UPDATE students SET credits=credits+? WHERE user_id=?",(amount,student_id))
    con.execute("""
      INSERT INTO credit_ledger(student_id,amount,kind,note,created_at)
      VALUES(?,?,?,?,?)
    """,(student_id,amount,"manual_adjustment",note,datetime.now().isoformat()))
    con.commit()
    con.close()

    flash("Τα credits του μαθητή ενημερώθηκαν.")
    return redirect(url_for("admin_student_profile",student_id=student_id))



@app.route("/admin/bookings")
def admin_bookings():
    """Central Admin bookings list with search, filters and edit/cancel actions."""
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    q=(request.args.get("q") or "").strip()
    date_filter=(request.args.get("date") or "").strip()
    instructor_filter=(request.args.get("instructor_id") or "").strip()
    spot_filter=(request.args.get("spot_id") or "").strip()
    status_filter=(request.args.get("status") or "all").strip().lower()

    params=[]
    where=["1=1"]
    if q:
        like=f"%{q}%"
        where.append("""EXISTS(
          SELECT 1 FROM booking_participants bpq
          JOIN users uq ON uq.id=bpq.student_id
          LEFT JOIN students sq ON sq.user_id=uq.id
          WHERE bpq.booking_id=b.id AND (
            uq.name LIKE ? OR COALESCE(uq.surname,'') LIKE ? OR uq.email LIKE ? OR
            COALESCE(uq.phone,'') LIKE ? OR COALESCE(sq.student_code,'') LIKE ?
          )
        )""")
        params.extend([like,like,like,like,like])
    if date_filter:
        try:
            date_filter=parse_gr_date(date_filter)
            where.append("s.lesson_date=?")
            params.append(date_filter)
        except ValueError:
            flash("Η ημερομηνία φίλτρου δεν είναι έγκυρη.")
            date_filter=""
    if instructor_filter:
        try:
            where.append("s.instructor_id=?")
            params.append(int(instructor_filter))
        except ValueError:
            instructor_filter=""
    if spot_filter:
        try:
            where.append("s.spot_id=?")
            params.append(int(spot_filter))
        except ValueError:
            spot_filter=""

    if status_filter=="booked":
        where.append("b.status='confirmed' AND COALESCE(b.payment_status,'')<>'pending'")
    elif status_filter=="pending":
        where.append("(b.status='pending_payment' OR b.payment_status='pending')")
    elif status_filter=="completed":
        where.append("b.status='completed'")
    elif status_filter=="no_show":
        where.append("b.status='no_show'")
    elif status_filter=="cancelled":
        where.append("b.status LIKE 'cancelled%'")
    else:
        status_filter="all"

    con=db()
    sql=f"""
      SELECT b.id,b.student_id,b.duration,b.status,b.payment_status,b.amount,b.created_at,b.completed_at,
             s.lesson_date,s.start_time,s.instructor_id,s.spot_id,
             su.name student_name,su.surname student_surname,su.email student_email,su.phone student_phone,
             (CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) student_level,st.student_code student_code,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names,
             (SELECT GROUP_CONCAT(ps.student_code, ' · ')
                FROM booking_participants bp4 JOIN students ps ON ps.user_id=bp4.student_id
               WHERE bp4.booking_id=b.id) participant_codes,
             iu.name instructor_name,iu.surname instructor_surname,iu.profile_photo instructor_photo,
             sp.name spot_name
      FROM bookings b
      JOIN slots s ON s.id=b.slot_id
      JOIN users su ON su.id=b.student_id
      LEFT JOIN students st ON st.user_id=su.id
      JOIN users iu ON iu.id=s.instructor_id
      LEFT JOIN spots sp ON sp.id=s.spot_id
      WHERE {' AND '.join(where)}
      ORDER BY s.lesson_date DESC,s.start_time DESC,b.id DESC
      LIMIT 250
    """
    bookings=con.execute(sql,params).fetchall()

    summary={
      "count":len(bookings),
      "hours":sum(float(r["duration"] or 0) for r in bookings if not str(r["status"] or "").startswith("cancelled")),
      "completed":sum(1 for r in bookings if r["status"]=="completed"),
      "no_show":sum(1 for r in bookings if r["status"]=="no_show"),
      "pending":sum(1 for r in bookings if r["status"]=="pending_payment" or r["payment_status"]=="pending"),
    }

    students=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,u.phone,s.level,s.credits,s.student_code,s.lesson_type,s.group_id
      FROM users u JOIN students s ON s.user_id=u.id
      WHERE COALESCE(u.active,1)=1
      ORDER BY u.name,u.surname
    """).fetchall()
    students=students_with_progress_levels(con, students)
    instructors=con.execute("""
      SELECT u.id,u.name,u.surname,u.profile_photo
      FROM users u JOIN instructors i ON i.user_id=u.id
      WHERE COALESCE(u.active,1)=1
      ORDER BY i.priority,u.name,u.surname
    """).fetchall()
    spots=con.execute("SELECT id,name FROM spots ORDER BY name").fetchall()

    # Edit modal choices are date-specific, matching the same rules used in the
    # day timetable editor. Build choices only for dates currently on screen.
    edit_schedule_data={}
    visible_dates=sorted({r["lesson_date"] for r in bookings})
    for lesson_date in visible_dates:
        cols=con.execute("""
          SELECT dc.instructor_id,u.name,u.surname
          FROM day_columns dc JOIN users u ON u.id=dc.instructor_id
          WHERE dc.lesson_date=? AND dc.instructor_id IS NOT NULL
          ORDER BY dc.column_no
        """,(lesson_date,)).fetchall()
        if not cols:
            cols=con.execute("""
              SELECT DISTINCT s.instructor_id,u.name,u.surname
              FROM slots s JOIN users u ON u.id=s.instructor_id
              WHERE s.lesson_date=?
              ORDER BY u.name,u.surname
            """,(lesson_date,)).fetchall()
        times=con.execute("""
          SELECT DISTINCT start_time FROM slots
          WHERE lesson_date=? ORDER BY start_time
        """,(lesson_date,)).fetchall()
        edit_schedule_data[lesson_date]={
          "instructors":[{
              "id":r["instructor_id"],
              "name":(r["name"] or "") + ((" " + r["surname"]) if r["surname"] else "")
          } for r in cols],
          "times":[r["start_time"] for r in times]
        }

    con.close()
    return render_template(
      "admin_bookings.html",
      bookings=bookings,summary=summary,students=students,instructors=instructors,spots=spots,
      edit_schedule_data=edit_schedule_data,
      filters={"q":q,"date":date_filter,"instructor_id":instructor_filter,"spot_id":spot_filter,"status":status_filter}
    )


@app.route("/admin/bookings/<int:booking_id>/history")
def admin_booking_history(booking_id):
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))
    con=db()
    booking=con.execute(f"""
      SELECT b.id,b.status,b.payment_status,b.duration,sl.lesson_date,sl.start_time,
             su.id student_id,su.name student_name,su.surname student_surname,{live_level_case('su.id')} AS student_level,
             st.student_code,iu.name instructor_name,iu.surname instructor_surname,COALESCE(day_sp.name,slot_sp.name) spot_name,
             (SELECT COUNT(*) FROM booking_participants bp WHERE bp.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp2 JOIN users pu ON pu.id=bp2.student_id
               WHERE bp2.booking_id=b.id) participant_names
      FROM bookings b
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users su ON su.id=b.student_id
      LEFT JOIN students st ON st.user_id=su.id
      JOIN users iu ON iu.id=sl.instructor_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE b.id=?
    """,(booking_id,)).fetchone()
    if not booking:
        con.close()
        flash("Η κράτηση δεν βρέθηκε.")
        return redirect(url_for("admin_bookings"))
    history=get_booking_audit(con,booking_id)
    con.close()
    return render_template("booking_history.html",booking=booking,history=history,back_url=url_for("admin_bookings"),back_label="‹ Επιστροφή στις κρατήσεις",page_title="Ιστορικό κράτησης")


@app.route("/admin/reports")
def admin_reports():
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    today=datetime.now().date()
    default_from=today.replace(day=1).isoformat()
    date_from=(request.args.get("from") or default_from).strip()
    date_to=(request.args.get("to") or today.isoformat()).strip()
    try:
        dfrom=datetime.strptime(date_from,"%Y-%m-%d").date()
        dto=datetime.strptime(date_to,"%Y-%m-%d").date()
        if dto<dfrom:
            dfrom,dto=dto,dfrom
            date_from,date_to=dfrom.isoformat(),dto.isoformat()
    except ValueError:
        dfrom=today.replace(day=1); dto=today
        date_from,date_to=dfrom.isoformat(),dto.isoformat()

    con=db()
    # Count occupied instructor time, not booking rows. Two students sharing an hour
    # are two student-hours but only one instructor-hour. Multi-hour bookings use
    # booking_slots (the authoritative occupied slots), including their second hour.
    occupied=con.execute("""
      SELECT DISTINCT b.id booking_id,b.status booking_status,b.duration booking_duration,
             occ.id slot_id,occ.lesson_date,occ.start_time,occ.duration slot_duration,
             occ.instructor_id,bp.student_id,
             COALESCE(bp.attendance_status,b.status) attendance_status,
             COALESCE(st.lesson_type,'private') lesson_type
      FROM bookings b
      JOIN booking_participants bp ON bp.booking_id=b.id
      JOIN booking_slots bs ON bs.booking_id=b.id
      JOIN slots occ ON occ.id=bs.slot_id
      LEFT JOIN students st ON st.user_id=bp.student_id
      WHERE occ.lesson_date BETWEEN ? AND ? AND b.status NOT LIKE 'cancelled%'
    """,(date_from,date_to)).fetchall()

    # Work at minute precision, which handles overlapping slots and fractional
    # durations without double-counting shared students/lessons.
    def time_minutes(value):
        hh,mm=map(int,str(value)[:5].split(':'))
        return hh*60+mm

    def merged_minutes(intervals):
        total=0; last_end=None
        for start,end in sorted(intervals):
            if last_end is None or start>last_end:
                total+=end-start; last_end=end
            elif end>last_end:
                total+=end-last_end; last_end=end
        return total

    physical_slots={}
    instructor_intervals={}
    completed_intervals={}
    for r in occupied:
        start_min=time_minutes(r['start_time'])
        end_min=start_min+int(round(float(r['slot_duration'] or 1)*60))
        key=(r['instructor_id'],r['lesson_date'])
        interval=(start_min,end_min)
        instructor_intervals.setdefault(key,set()).add(interval)
        completed=(r['attendance_status']=='completed')
        if completed:
            completed_intervals.setdefault(key,set()).add(interval)
        slot=physical_slots.setdefault((key,r['slot_id']),{
            'lesson_date':r['lesson_date'],'duration':float(r['slot_duration'] or 1),
            'students':set(),'types':set(),'completed':False})
        slot['students'].add(r['student_id'])
        slot['types'].add(r['lesson_type'])
        slot['completed'] |= completed

    booked_hours=sum(merged_minutes(v) for v in instructor_intervals.values())/60.0
    completed_hours=sum(merged_minutes(v) for v in completed_intervals.values())/60.0
    shared_hours=sum(r['duration'] for r in physical_slots.values() if len(r['students'])>1)
    lesson_mix={'private':0.0,'2p':0.0,'3p':0.0,'shared':0.0}
    for r in physical_slots.values():
        kind=('3p' if '3p' in r['types'] else '2p' if '2p' in r['types']
              else 'shared' if len(r['students'])>1 else 'private')
        lesson_mix[kind]+=r['duration']

    attendance=con.execute("""
      SELECT COALESCE(bp.attendance_status,b.status) st, COUNT(*) n,
             COALESCE(SUM(b.duration),0) h
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id
      JOIN slots s ON s.id=b.slot_id
      WHERE s.lesson_date BETWEEN ? AND ?
      GROUP BY COALESCE(bp.attendance_status,b.status)
    """,(date_from,date_to)).fetchall()
    att={r['st']:{'count':int(r['n'] or 0),'hours':float(r['h'] or 0)} for r in attendance}

    instructor_rows=con.execute("""
      SELECT u.id,u.name,u.surname,u.profile_photo,i.hourly_rate
      FROM users u JOIN instructors i ON i.user_id=u.id
      WHERE COALESCE(u.active,1)=1
      ORDER BY u.name,u.surname
    """).fetchall()
    instructors=[]; estimated_pay=0.0
    for r in instructor_rows:
        x=dict(r); iid=x['id']
        x['booked_hours']=sum(merged_minutes(v) for (inst,_),v in instructor_intervals.items() if inst==iid)/60.0
        x['completed_hours']=sum(merged_minutes(v) for (inst,_),v in completed_intervals.items() if inst==iid)/60.0
        x['estimated_pay']=x['completed_hours']*float(x['hourly_rate'] or 0)
        estimated_pay+=x['estimated_pay']; instructors.append(x)
    instructors.sort(key=lambda r:(-r['completed_hours'],r['name'] or '',r['surname'] or ''))

    # These are *student-hours*, not count of booking records.
    top_students=con.execute("""
      SELECT u.id,u.name,u.surname,s.student_code,
             COALESCE(SUM(b.duration),0) lesson_hours,
             COALESCE(SUM(CASE WHEN COALESCE(bp.attendance_status,b.status)='completed'
                       THEN b.duration ELSE 0 END),0) completed_hours
      FROM booking_participants bp
      JOIN bookings b ON b.id=bp.booking_id JOIN slots sl ON sl.id=b.slot_id
      JOIN users u ON u.id=bp.student_id JOIN students s ON s.user_id=u.id
      WHERE sl.lesson_date BETWEEN ? AND ? AND b.status NOT LIKE 'cancelled%'
      GROUP BY u.id ORDER BY lesson_hours DESC,u.name,u.surname LIMIT 10
    """,(date_from,date_to)).fetchall()

    # Reports revenue must mean CASH RECEIVED IN THE SELECTED PERIOD, exactly
    # as Finance: installments count when received; negotiated discounts never
    # count as cash. Keep paid purchase counts as their own separate metric.
    sales=con.execute("""
      SELECT COALESCE(package_type,'lesson') package_type,COUNT(*) n
      FROM student_packages
      WHERE payment_status='paid' AND substr(COALESCE(paid_at,purchased_at),1,10) BETWEEN ? AND ?
      GROUP BY COALESCE(package_type,'lesson')
    """,(date_from,date_to)).fetchall()
    sales_map={r["package_type"]:{"count":int(r["n"]),"revenue":0.0} for r in sales}
    receipts=con.execute("""
      SELECT COALESCE(sp.package_type,'lesson') package_type,
             COALESCE(SUM(py.amount),0) revenue
      FROM student_payments py JOIN student_packages sp ON sp.id=py.purchase_id
      WHERE py.payment_date BETWEEN ? AND ?
      GROUP BY COALESCE(sp.package_type,'lesson')
    """,(date_from,date_to)).fetchall()
    for r in receipts:
        sales_map.setdefault(r["package_type"],{"count":0,"revenue":0.0})["revenue"]+=float(r["revenue"] or 0)
    # Older imports may have a paid purchase without individual receipt rows.
    # Finance intentionally includes these, but never counts them twice.
    legacy_receipts=con.execute("""
      SELECT COALESCE(sp.package_type,'lesson') package_type,
             COALESCE(SUM(sp.price),0) revenue
      FROM student_packages sp
      WHERE sp.payment_status='paid'
        AND substr(COALESCE(sp.paid_at,sp.purchased_at),1,10) BETWEEN ? AND ?
        AND NOT EXISTS(SELECT 1 FROM student_payments py WHERE py.purchase_id=sp.id)
      GROUP BY COALESCE(sp.package_type,'lesson')
    """,(date_from,date_to)).fetchall()
    for r in legacy_receipts:
        sales_map.setdefault(r["package_type"],{"count":0,"revenue":0.0})["revenue"]+=float(r["revenue"] or 0)
    total_revenue=sum(v["revenue"] for v in sales_map.values())
    instructor_paid=float(con.execute("""SELECT COALESCE(SUM(amount),0) v FROM instructor_payments WHERE payment_date BETWEEN ? AND ?""",(date_from,date_to)).fetchone()["v"] or 0)
    active_students=int(con.execute("""
      SELECT COUNT(DISTINCT bp.student_id) n FROM booking_participants bp JOIN bookings b ON b.id=bp.booking_id
      JOIN slots s ON s.id=b.slot_id WHERE s.lesson_date BETWEEN ? AND ? AND b.status NOT LIKE 'cancelled%'
    """,(date_from,date_to)).fetchone()["n"] or 0)
    today_iso=today.isoformat()
    crew_active=int(con.execute("""SELECT COUNT(*) n FROM students WHERE crew_member=1 AND (crew_start_date IS NULL OR crew_start_date<=?) AND (crew_end_date IS NULL OR crew_end_date>=?)""",(today_iso,today_iso)).fetchone()["n"] or 0)
    crew_expired=int(con.execute("""SELECT COUNT(*) n FROM students WHERE crew_member=1 AND crew_end_date IS NOT NULL AND crew_end_date<?""",(today_iso,)).fetchone()["n"] or 0)

    # Weekly completed hours for a compact chart, Monday buckets.
    weeks=[]; cur=dfrom-timedelta(days=dfrom.weekday())
    while cur<=dto:
        end=min(cur+timedelta(days=6),dto)
        val=sum(merged_minutes(intervals) for (iid,day),intervals in completed_intervals.items()
                if cur.isoformat()<=day<=end.isoformat())/60.0
        weeks.append({"label":cur.strftime("%d/%m"),"value":val})
        cur+=timedelta(days=7)
    max_week=max([w["value"] for w in weeks],default=0) or 1
    con.close()
    summary={
      "booked_hours":booked_hours,"completed_hours":completed_hours,"shared_hours":shared_hours,
      "no_show":att.get("no_show",{}).get("count",0),"cancelled":sum(v["count"] for k,v in att.items() if str(k).startswith("cancelled")),
      "active_students":active_students,"revenue":total_revenue,"instructor_paid":instructor_paid,
      "instructor_balance":max(0.0,estimated_pay-instructor_paid),"crew_active":crew_active,"crew_expired":crew_expired,
      "package_sales":sales_map.get("lesson",{}).get("count",0),"crew_sales":sales_map.get("crew",{}).get("count",0)
    }
    return render_template("admin_reports.html",summary=summary,instructors=instructors,top_students=top_students,
                           weeks=weeks,max_week=max_week,date_from=date_from,date_to=date_to,sales_map=sales_map,lesson_mix=lesson_mix)


@app.route("/admin/finance")
def admin_finance():
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))

    today=datetime.now().date()
    month_raw=(request.args.get("month") or today.strftime("%Y-%m")).strip()
    try:
        month_start=datetime.strptime(month_raw+"-01","%Y-%m-%d").date()
    except ValueError:
        month_start=today.replace(day=1)
        month_raw=month_start.strftime("%Y-%m")
    if month_start.month==12:
        next_month=month_start.replace(year=month_start.year+1,month=1,day=1)
    else:
        next_month=month_start.replace(month=month_start.month+1,day=1)
    month_end=next_month-timedelta(days=1)
    if month_start.month==1:
        prev_start=month_start.replace(year=month_start.year-1,month=12,day=1)
    else:
        prev_start=month_start.replace(month=month_start.month-1,day=1)
    prev_end=month_start-timedelta(days=1)

    date_from=month_start.isoformat(); date_to=month_end.isoformat()
    prev_from=prev_start.isoformat(); prev_to=prev_end.isoformat()
    con=db()

    def paid_revenue(d1,d2,ptype=None):
        sql="""SELECT COALESCE(SUM(py.amount),0) v FROM student_payments py JOIN student_packages sp ON sp.id=py.purchase_id WHERE py.payment_date BETWEEN ? AND ?"""
        params=[d1,d2]
        if ptype: sql += " AND COALESCE(sp.package_type,'lesson')=?"; params.append(ptype)
        cash=float(con.execute(sql,params).fetchone()["v"] or 0)
        legacy_sql="""SELECT COALESCE(SUM(sp.price),0) v FROM student_packages sp WHERE sp.payment_status='paid' AND substr(COALESCE(sp.paid_at,sp.purchased_at),1,10) BETWEEN ? AND ? AND NOT EXISTS(SELECT 1 FROM student_payments py WHERE py.purchase_id=sp.id)"""
        legacy_params=[d1,d2]
        if ptype: legacy_sql += " AND COALESCE(sp.package_type,'lesson')=?"; legacy_params.append(ptype)
        return cash+float(con.execute(legacy_sql,legacy_params).fetchone()["v"] or 0)

    lesson_revenue=paid_revenue(date_from,date_to,"lesson")
    crew_revenue=paid_revenue(date_from,date_to,"crew")
    total_revenue=lesson_revenue+crew_revenue
    prev_revenue=paid_revenue(prev_from,prev_to)
    revenue_change=None if prev_revenue==0 else ((total_revenue-prev_revenue)/prev_revenue)*100

    instructor_paid=float(con.execute("""SELECT COALESCE(SUM(amount),0) v FROM instructor_payments
                                        WHERE payment_date BETWEEN ? AND ?""",(date_from,date_to)).fetchone()["v"] or 0)

    instructor_earned=float(con.execute("""
      SELECT COALESCE(SUM(ih.hours * COALESCE(i.hourly_rate,0)),0) v
      FROM instructor_hours ih JOIN instructors i ON i.user_id=ih.instructor_id
      WHERE ih.lesson_date BETWEEN ? AND ?
    """,(date_from,date_to)).fetchone()["v"] or 0)
    instructor_balance=max(0.0,instructor_earned-instructor_paid)

    pending_packages=float(con.execute("""
      SELECT COALESCE(SUM(MAX(0,price-COALESCE(paid_amount,0))),0) v FROM student_packages
      WHERE payment_status IN ('unpaid','partial','pending') AND substr(purchased_at,1,10) BETWEEN ? AND ?
    """,(date_from,date_to)).fetchone()["v"] or 0)
    pending_bookings=float(con.execute("""
      SELECT COALESCE(SUM(bp.amount),0) v
      FROM booking_participants bp JOIN bookings b ON b.id=bp.booking_id JOIN slots s ON s.id=b.slot_id
      WHERE bp.payment_status='pending' AND s.lesson_date BETWEEN ? AND ? AND b.status NOT LIKE 'cancelled%'
    """,(date_from,date_to)).fetchone()["v"] or 0)
    pending_total=pending_packages+pending_bookings

    net_cash=total_revenue-instructor_paid

    sales_rows=con.execute("""
      SELECT package_name,COALESCE(package_type,'lesson') package_type,COUNT(*) sales,COALESCE(SUM(price),0) revenue
      FROM student_packages
      WHERE payment_status='paid' AND substr(COALESCE(paid_at,purchased_at),1,10) BETWEEN ? AND ?
      GROUP BY package_name,COALESCE(package_type,'lesson')
      ORDER BY revenue DESC,sales DESC,package_name
    """,(date_from,date_to)).fetchall()

    payment_rows=con.execute("""
      SELECT ip.payment_date,ip.amount,ip.note,u.name,u.surname
      FROM instructor_payments ip JOIN users u ON u.id=ip.instructor_id
      WHERE ip.payment_date BETWEEN ? AND ?
      ORDER BY ip.payment_date DESC,ip.id DESC LIMIT 30
    """,(date_from,date_to)).fetchall()

    recent_sales=con.execute("""
      SELECT sp.id,sp.package_name,sp.package_type,sp.price,sp.payment_status,
             substr(COALESCE(sp.paid_at,sp.purchased_at),1,10) sale_date,u.name,u.surname,s.student_code
      FROM student_packages sp JOIN users u ON u.id=sp.student_id LEFT JOIN students s ON s.user_id=u.id
      WHERE substr(COALESCE(sp.paid_at,sp.purchased_at),1,10) BETWEEN ? AND ?
      ORDER BY COALESCE(sp.paid_at,sp.purchased_at) DESC,sp.id DESC LIMIT 40
    """,(date_from,date_to)).fetchall()

    # Weekly cash-in buckets for selected month.
    weeks=[]
    cur=month_start
    idx=1
    while cur<=month_end:
        wend=min(cur+timedelta(days=6),month_end)
        val=paid_revenue(cur.isoformat(),wend.isoformat())
        weeks.append({"label":f"{cur.strftime('%d/%m')}–{wend.strftime('%d/%m')}","value":round(val,2)})
        cur=wend+timedelta(days=1); idx+=1
    max_week=max([w["value"] for w in weeks],default=0) or 1

    # Current Crew season shortcut label.
    crew_from,crew_to=crew_season_for_date(today)
    month_names={1:'Ιανουάριος',2:'Φεβρουάριος',3:'Μάρτιος',4:'Απρίλιος',5:'Μάιος',6:'Ιούνιος',7:'Ιούλιος',8:'Αύγουστος',9:'Σεπτέμβριος',10:'Οκτώβριος',11:'Νοέμβριος',12:'Δεκέμβριος'}
    month_label=f"{month_names.get(month_start.month,month_start.strftime('%m'))} {month_start.year}"
    prev_label=f"{month_names.get(prev_start.month,prev_start.strftime('%m'))} {prev_start.year}"

    con.close()
    summary={
      "lesson_revenue":lesson_revenue,"crew_revenue":crew_revenue,"total_revenue":total_revenue,
      "prev_revenue":prev_revenue,"revenue_change":revenue_change,"instructor_paid":instructor_paid,
      "instructor_earned":instructor_earned,"instructor_balance":instructor_balance,
      "pending_packages":pending_packages,"pending_bookings":pending_bookings,"pending_total":pending_total,
      "net_cash":net_cash
    }
    return render_template("admin_finance.html",summary=summary,sales_rows=sales_rows,payment_rows=payment_rows,
                           recent_sales=recent_sales,weeks=weeks,max_week=max_week,month=month_raw,
                           month_label=month_label,prev_label=prev_label,crew_from=crew_from,crew_to=crew_to)

@app.route("/admin/packages")
def admin_packages():
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))
    con=db()
    packages=con.execute("SELECT * FROM packages ORDER BY active DESC,CASE WHEN package_type='crew' THEN 0 ELSE 1 END,hours,price,id").fetchall()
    students=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,s.credits
      FROM users u JOIN students s ON s.user_id=u.id
      WHERE COALESCE(u.active,1)=1
      ORDER BY u.name,u.surname
    """).fetchall()
    purchases=con.execute("""
      SELECT sp.*,u.name student_name,u.surname student_surname
      FROM student_packages sp JOIN users u ON u.id=sp.student_id
      ORDER BY sp.purchased_at DESC,sp.id DESC LIMIT 100
    """).fetchall()
    con.close()
    return render_template("admin_packages.html",packages=packages,students=students,purchases=purchases)


@app.post("/admin/packages/create")
def admin_package_create():
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))
    name=(request.form.get("name") or "").strip()
    package_type=(request.form.get("package_type") or "lesson").strip().lower()
    if package_type not in ("lesson","crew"):
        package_type="lesson"
    try:
        hours=float(request.form.get("hours") or 0)
        price=float(request.form.get("price") or 0)
    except (TypeError,ValueError):
        hours=0; price=0
    if package_type=="crew":
        hours=0.0
    if not name or (package_type=="lesson" and hours<=0) or price<0:
        flash("Συμπλήρωσε σωστά τα στοιχεία του πακέτου.")
        return redirect(url_for("admin_packages"))
    con=db()
    con.execute("INSERT INTO packages(name,hours,price,active,created_at,package_type,activation_rule) VALUES(?,?,?,?,?,?,?)",
                (name,hours,price,1,datetime.now().isoformat(),package_type,"paid_only"))
    con.commit(); con.close()
    flash("Το πακέτο δημιουργήθηκε.")
    return redirect(url_for("admin_packages"))


@app.post("/admin/packages/<int:package_id>/toggle")
def admin_package_toggle(package_id):
    u=current_user()
    if not u or u["role"]!="admin":
        return redirect(url_for("login"))
    con=db()
    row=con.execute("SELECT active FROM packages WHERE id=?",(package_id,)).fetchone()
    if not row:
        con.close(); flash("Το πακέτο δεν βρέθηκε.")
        return redirect(url_for("admin_packages"))
    con.execute("UPDATE packages SET active=? WHERE id=?",(0 if row["active"] else 1,package_id))
    con.commit(); con.close()
    flash("Η κατάσταση του πακέτου ενημερώθηκε.")
    return redirect(url_for("admin_packages"))


@app.post("/admin/students/<int:student_id>/packages/purchase")
def admin_student_package_purchase(student_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    try: package_id=int(request.form.get("package_id") or 0)
    except (TypeError,ValueError): package_id=0
    payment_status=(request.form.get("payment_status") or "unpaid").strip().lower()
    if payment_status not in ("paid","unpaid"): payment_status="unpaid"
    note=(request.form.get("note") or "").strip(); con=db(); con.execute("BEGIN IMMEDIATE")
    student=con.execute("SELECT user_id FROM students WHERE user_id=?",(student_id,)).fetchone(); package=con.execute("SELECT * FROM packages WHERE id=? AND active=1",(package_id,)).fetchone()
    if not student or not package:
        con.rollback(); con.close(); flash("Ο μαθητής ή το πακέτο δεν βρέθηκε."); return redirect(url_for("admin_student_profile",student_id=student_id))
    now=datetime.now().isoformat(); package_type=(package["package_type"] or "lesson"); rule=(package["activation_rule"] or "paid_only"); valid_from=valid_until=None
    if package_type=="crew": valid_from,valid_until=crew_season_for_date(datetime.now().date())
    paid_amount=float(package["price"] or 0) if payment_status=="paid" else 0.0
    cur=con.execute("""INSERT INTO student_packages(student_id,package_id,package_name,hours_total,hours_remaining,price,payment_status,purchased_at,paid_at,note,package_type,valid_from,valid_until,activation_rule,paid_amount,credits_activated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(student_id,package["id"],package["name"],float(package["hours"] or 0),0.0,float(package["price"] or 0),payment_status,now,now if payment_status=="paid" else None,note,package_type,valid_from,valid_until,rule,paid_amount,0))
    purchase=con.execute("SELECT * FROM student_packages WHERE id=?",(cur.lastrowid,)).fetchone()
    if package_type=="lesson" and (rule=="immediate" or payment_status=="paid"): _activate_student_purchase(con,purchase,"Package purchase")
    if payment_status=="paid" and float(package["price"] or 0)>0:
        con.execute("INSERT INTO student_payments(student_id,purchase_id,amount,payment_date,method,note,created_at) VALUES(?,?,?,?,?,?,?)",(student_id,purchase["id"],float(package["price"] or 0),datetime.now().date().isoformat(),"manual",note,now))
    if payment_status=="paid" and package_type=="crew": con.execute("UPDATE students SET crew_member=1,crew_start_date=?,crew_end_date=?,crew_fee=? WHERE user_id=?",(valid_from,valid_until,float(package["price"] or 0),student_id))
    con.commit(); con.close(); flash(f"Το {package['name']} καταχωρήθηκε ως {'Paid' if payment_status=='paid' else 'Unpaid'}.")
    return redirect(url_for("admin_student_profile",student_id=student_id))

@app.post("/admin/package-purchases/<int:purchase_id>/payments/add")
def admin_package_purchase_add_payment(purchase_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    # Each displayed form gets its own one-use ID. A browser retry of the
    # same POST cannot charge the package twice, even if balance remains.
    request_id=(request.form.get("payment_request_id") or "").strip()
    if not (24 <= len(request_id) <= 128 and re.fullmatch(r"[A-Za-z0-9_-]+", request_id)):
        abort(400, description="Missing or invalid payment request ID. Refresh the page.")
    con=db(); con.execute("BEGIN IMMEDIATE"); purchase=con.execute("SELECT * FROM student_packages WHERE id=?",(purchase_id,)).fetchone()
    if not purchase:
        con.rollback(); con.close(); flash("Η αγορά δεν βρέθηκε."); return redirect(url_for("admin_packages"))
    price=float(purchase["price"] or 0); already=float(purchase["paid_amount"] or 0); balance=max(0.0,price-already)
    try: amount=float(request.form.get("amount") or 0)
    except (TypeError,ValueError): amount=0
    # An installment reduces the outstanding balance. A final settlement can be
    # less than the advertised price: the admin explicitly agrees to a reduced
    # FINAL purchase price (not a phantom payment or debt write-off).
    action=(request.form.get("payment_action") or "installment").strip()
    if action not in {"installment", "settle"}:
        con.rollback(); con.close(); abort(400, description="Invalid payment action")
    if not math.isfinite(amount) or round(amount,2)!=amount:
        con.rollback(); con.close(); flash("Βάλε έγκυρο ποσό με έως 2 δεκαδικά."); return redirect(url_for("admin_student_profile",student_id=purchase["student_id"]))
    if amount<=0 or amount>balance+0.001:
        con.rollback(); con.close(); flash("Το ποσό πληρωμής δεν είναι έγκυρο."); return redirect(url_for("admin_student_profile",student_id=purchase["student_id"]))
    # Durable idempotency ledger: the key is committed atomically alongside
    # the payment and credit activation. Rolled-back attempts do not consume it.
    inserted=con.execute("INSERT OR IGNORE INTO package_payment_requests(request_id,purchase_id,created_at) VALUES(?,?,?)",(request_id,purchase_id,datetime.now().isoformat()))
    if inserted.rowcount != 1:
        con.rollback(); con.close()
        flash("Αυτή η πληρωμή έχει ήδη υποβληθεί. Δεν καταχωρήθηκε δεύτερη φορά.")
        return redirect(url_for("admin_student_profile",student_id=purchase["student_id"]))
    method=(request.form.get("method") or "manual").strip(); note=(request.form.get("note") or ("Εξόφληση" if action=="settle" else "Δόση")).strip(); now=datetime.now().isoformat()
    new_paid=round(already+amount,2)
    # For final settlement, the recorded sale price becomes the negotiated total.
    # The difference is NOT recorded as cash received. Both original price and
    # discount remain in the purchase/payment notes for auditability.
    discount=round(max(0.0,price-new_paid),2) if action=="settle" else 0.0
    final_price=new_paid if action=="settle" else price
    new_status=_purchase_payment_status(final_price,new_paid)
    if action=="settle" and discount>0:
        discount_note=f"Συμφωνημένη τελική τιμή {final_price:.2f}€ (αρχική {price:.2f}€, έκπτωση {discount:.2f}€)"
        note=(note+" · "+discount_note) if note else discount_note
        previous_note=(purchase["note"] or "").strip()
        updated_note=(previous_note+" | "+discount_note) if previous_note else discount_note
        con.execute("UPDATE student_packages SET price=?, paid_amount=?, payment_status=?, paid_at=?, note=? WHERE id=?",(final_price,new_paid,"paid",now,updated_note,purchase_id))
    else:
        con.execute("UPDATE student_packages SET paid_amount=?,payment_status=?,paid_at=CASE WHEN ?='paid' THEN ? ELSE paid_at END WHERE id=?",(new_paid,new_status,new_status,now,purchase_id))
    con.execute("INSERT INTO student_payments(student_id,purchase_id,amount,payment_date,method,note,created_at) VALUES(?,?,?,?,?,?,?)",(purchase["student_id"],purchase_id,amount,datetime.now().date().isoformat(),method,note,now))
    purchase=con.execute("SELECT * FROM student_packages WHERE id=?",(purchase_id,)).fetchone(); rule=(purchase["activation_rule"] or "paid_only")
    if (purchase["package_type"] or "lesson")=="lesson" and int(purchase["credits_activated"] or 0)==0:
        if rule=="first_payment" and new_paid>0: _activate_student_purchase(con,purchase,"First payment")
        elif rule=="paid_only" and new_status=="paid": _activate_student_purchase(con,purchase,"Full payment")
    if (purchase["package_type"] or "lesson")=="crew" and new_status=="paid":
        vf=purchase["valid_from"]; vu=purchase["valid_until"]
        if not vf or not vu:
            vf,vu=crew_season_for_date(datetime.now().date()); con.execute("UPDATE student_packages SET valid_from=?,valid_until=? WHERE id=?",(vf,vu,purchase_id))
        con.execute("UPDATE students SET crew_member=1,crew_start_date=?,crew_end_date=?,crew_fee=? WHERE user_id=?",(vf,vu,final_price,purchase["student_id"]))
    con.commit(); con.close(); flash(f"Καταχωρήθηκε πληρωμή {amount:.2f}€. Υπόλοιπο {max(0,final_price-new_paid):.2f}€." + (f" Τελική συμφωνημένη τιμή {final_price:.2f}€ (έκπτωση {discount:.2f}€)." if discount>0 else ""))
    return redirect(url_for("admin_student_profile",student_id=purchase["student_id"]))

@app.post("/admin/package-purchases/<int:purchase_id>/mark-paid")
def admin_package_purchase_mark_paid(purchase_id):
    u=current_user()
    if not u or u["role"]!="admin": return redirect(url_for("login"))
    con=db(); con.execute("BEGIN IMMEDIATE"); purchase=con.execute("SELECT * FROM student_packages WHERE id=?",(purchase_id,)).fetchone()
    if not purchase:
        con.rollback(); con.close(); flash("Η αγορά πακέτου δεν βρέθηκε."); return redirect(url_for("admin_packages"))
    balance=max(0.0,float(purchase["price"] or 0)-float(purchase["paid_amount"] or 0))
    if balance<=0:
        con.rollback(); con.close(); flash("Η αγορά είναι ήδη εξοφλημένη."); return redirect(url_for("admin_student_profile",student_id=purchase["student_id"]))
    now=datetime.now().isoformat(); con.execute("UPDATE student_packages SET paid_amount=price,payment_status='paid',paid_at=? WHERE id=?",(now,purchase_id))
    con.execute("INSERT INTO student_payments(student_id,purchase_id,amount,payment_date,method,note,created_at) VALUES(?,?,?,?,?,?,?)",(purchase["student_id"],purchase_id,balance,datetime.now().date().isoformat(),"manual","Mark paid",now))
    purchase=con.execute("SELECT * FROM student_packages WHERE id=?",(purchase_id,)).fetchone()
    if (purchase["package_type"] or "lesson")=="lesson" and int(purchase["credits_activated"] or 0)==0: _activate_student_purchase(con,purchase,"Full payment")
    if (purchase["package_type"] or "lesson")=="crew":
        vf=purchase["valid_from"]; vu=purchase["valid_until"]
        if not vf or not vu:
            vf,vu=crew_season_for_date(datetime.now().date()); con.execute("UPDATE student_packages SET valid_from=?,valid_until=? WHERE id=?",(vf,vu,purchase_id))
        con.execute("UPDATE students SET crew_member=1,crew_start_date=?,crew_end_date=?,crew_fee=? WHERE user_id=?",(vf,vu,float(purchase["price"] or 0),purchase["student_id"]))
    con.commit(); con.close(); flash("Η αγορά εξοφλήθηκε.")
    return redirect(url_for("admin_student_profile",student_id=purchase["student_id"]))


@app.route("/instructor")
def instructor():
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))

    raw_date=request.args.get("date")
    try:
        date=parse_gr_date(raw_date) if raw_date else datetime.now().date().isoformat()
    except ValueError:
        date=datetime.now().date().isoformat()

    sync_day_spot(date)
    repair_booking_slot_links(date)
    con=db()

    # One row per booking, filtered to this instructor and selected day.
    booking_rows=con.execute("""
      SELECT b.*,su.name student,su.surname student_surname,su.phone student_phone,
             su.profile_photo student_photo,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) AS level,s.start_time,s.lesson_date,
             COALESCE(day_sp.name,slot_sp.name) spot,s.instructor_id,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM bookings b
      JOIN slots s ON s.id=b.slot_id
      JOIN users su ON su.id=b.student_id
      LEFT JOIN students st ON st.user_id=su.id
      JOIN spots slot_sp ON slot_sp.id=s.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=s.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE s.instructor_id=? AND s.lesson_date=?
        AND b.status NOT LIKE 'cancelled%'
      ORDER BY s.start_time
    """,(u["id"],date)).fetchall()

    bookings=[]
    for row in booking_rows:
        item=dict(row)
        try:
            start_dt=datetime.strptime(row["start_time"],"%H:%M")
            end_dt=start_dt+timedelta(hours=float(row["duration"] or 1))
            item["end_time"]=end_dt.strftime("%H:%M")
        except Exception:
            item["end_time"]=row["start_time"]
        bookings.append(item)

    skills=con.execute("SELECT * FROM skills ORDER BY id").fetchall()

    instructor_info=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,u.phone,u.profile_photo,
             i.hourly_rate,i.activation_threshold
      FROM users u JOIN instructors i ON i.user_id=u.id
      WHERE u.id=?
    """,(u["id"],)).fetchone()

    total_hours=con.execute("""
      SELECT COALESCE(SUM(hours),0) h
      FROM instructor_hours
      WHERE instructor_id=?
    """,(u["id"],)).fetchone()["h"]

    selected_day_hours=con.execute("""
      SELECT COALESCE(SUM(hours),0) h
      FROM instructor_hours
      WHERE instructor_id=? AND lesson_date=?
    """,(u["id"],date)).fetchone()["h"]

    total_lessons=len(bookings)
    completed_lessons=sum(1 for b in bookings if b["status"]=="completed")
    no_show_lessons=sum(1 for b in bookings if b["status"]=="no_show")
    pending_lessons=sum(1 for b in bookings if b["status"] not in ("completed","no_show"))
    pending_hours=sum(float(b["duration"] or 0) for b in bookings if b["status"] not in ("completed","no_show"))

    # Weekly instructor calendar.
    selected_dt=datetime.strptime(date,"%Y-%m-%d").date()
    week_start=selected_dt-timedelta(days=selected_dt.weekday())
    greek_days=["Δευτέρα","Τρίτη","Τετάρτη","Πέμπτη","Παρασκευή","Σάββατο","Κυριακή"]
    week_days=[]

    for idx in range(7):
        d=week_start+timedelta(days=idx)
        iso=d.isoformat()

        count=con.execute("""
          SELECT COUNT(*) n
          FROM bookings b
          JOIN slots s ON s.id=b.slot_id
          WHERE s.instructor_id=? AND s.lesson_date=?
            AND b.status NOT LIKE 'cancelled%'
        """,(u["id"],iso)).fetchone()["n"]

        booked_hours=con.execute("""
          SELECT COALESCE(SUM(b.duration),0) h
          FROM bookings b
          JOIN slots s ON s.id=b.slot_id
          WHERE s.instructor_id=? AND s.lesson_date=?
            AND b.status NOT LIKE 'cancelled%'
        """,(u["id"],iso)).fetchone()["h"]

        spot=con.execute("""
          SELECT sp.name
          FROM day_spots ds
          JOIN spots sp ON sp.id=ds.spot_id
          WHERE ds.lesson_date=?
        """,(iso,)).fetchone()

        week_days.append({
          "iso":iso,
          "label":greek_days[idx],
          "count":count,
          "hours":booked_hours,
          "spot":spot["name"] if spot else None,
          "selected":iso==date
        })

    prev_week=(week_start-timedelta(days=7)).isoformat()
    next_week=(week_start+timedelta(days=7)).isoformat()
    week_end=(week_start+timedelta(days=6)).isoformat()

    week_hour_rows=[]
    week_total_hours=0
    week_completed_lessons=0
    for idx in range(7):
        d=week_start+timedelta(days=idx)
        iso=d.isoformat()
        row=con.execute("""
          SELECT COUNT(DISTINCT booking_id) lessons, COALESCE(SUM(hours),0) h
          FROM instructor_hours
          WHERE instructor_id=? AND lesson_date=?
        """,(u["id"],iso)).fetchone()
        lessons=row["lessons"] or 0
        hrs=float(row["h"] or 0)
        week_completed_lessons+=lessons
        week_total_hours+=hrs
        week_hour_rows.append({
          "iso":iso,
          "label":greek_days[idx],
          "lessons":lessons,
          "hours":hrs
        })

    selected_spot=con.execute("""
      SELECT sp.* FROM day_spots ds
      JOIN spots sp ON sp.id=ds.spot_id
      WHERE ds.lesson_date=?
    """,(date,)).fetchone()

    hourly_rate=float(instructor_info["hourly_rate"] or 0) if instructor_info else 0.0
    day_estimated_pay=float(selected_day_hours or 0)*hourly_rate
    week_estimated_pay=float(week_total_hours or 0)*hourly_rate

    con.close()

    return render_template(
      "instructor.html",
      instructor=instructor_info,
      selected_spot=selected_spot,
      day_estimated_pay=day_estimated_pay,
      week_estimated_pay=week_estimated_pay,
      bookings=bookings,
      skills=skills,
      hours=total_hours,
      day_hours=selected_day_hours,
      total_lessons=total_lessons,
      completed_lessons=completed_lessons,
      no_show_lessons=no_show_lessons,
      pending_lessons=pending_lessons,
      pending_hours=pending_hours,
      date=date,
      week_days=week_days,
      prev_week=prev_week,
      next_week=next_week,
      week_start=week_start.isoformat(),
      week_end=week_end,
      week_hour_rows=week_hour_rows,
      week_total_hours=week_total_hours,
      week_completed_lessons=week_completed_lessons
    )


@app.route("/instructor/profile")
def instructor_profile():
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))
    con=db()
    inst=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,u.phone,u.instagram,u.profile_photo,
             i.priority,i.activation_threshold,i.hourly_rate
      FROM instructors i JOIN users u ON u.id=i.user_id
      WHERE u.id=?
    """,(u["id"],)).fetchone()

    now_dt=datetime.now(); today=now_dt.date()
    week_start=today-timedelta(days=today.weekday()); week_end=week_start+timedelta(days=6)
    month_start=today.replace(day=1)
    if today.month==12:
        next_month=today.replace(year=today.year+1,month=1,day=1)
    else:
        next_month=today.replace(month=today.month+1,day=1)
    month_end=next_month-timedelta(days=1)

    total_hours=float(con.execute("SELECT COALESCE(SUM(hours),0) h FROM instructor_hours WHERE instructor_id=?",(u["id"],)).fetchone()["h"] or 0)
    day_hours=float(con.execute("SELECT COALESCE(SUM(hours),0) h FROM instructor_hours WHERE instructor_id=? AND lesson_date=?",(u["id"],today.isoformat())).fetchone()["h"] or 0)
    week_hours=float(con.execute("SELECT COALESCE(SUM(hours),0) h FROM instructor_hours WHERE instructor_id=? AND lesson_date BETWEEN ? AND ?",(u["id"],week_start.isoformat(),week_end.isoformat())).fetchone()["h"] or 0)
    month_hours=float(con.execute("SELECT COALESCE(SUM(hours),0) h FROM instructor_hours WHERE instructor_id=? AND lesson_date BETWEEN ? AND ?",(u["id"],month_start.isoformat(),month_end.isoformat())).fetchone()["h"] or 0)

    completed_lessons=int(con.execute("SELECT COUNT(DISTINCT booking_id) n FROM instructor_hours WHERE instructor_id=?",(u["id"],)).fetchone()["n"] or 0)
    day_lessons=int(con.execute("SELECT COUNT(DISTINCT booking_id) n FROM instructor_hours WHERE instructor_id=? AND lesson_date=?",(u["id"],today.isoformat())).fetchone()["n"] or 0)
    week_lessons=int(con.execute("SELECT COUNT(DISTINCT booking_id) n FROM instructor_hours WHERE instructor_id=? AND lesson_date BETWEEN ? AND ?",(u["id"],week_start.isoformat(),week_end.isoformat())).fetchone()["n"] or 0)
    month_lessons=int(con.execute("SELECT COUNT(DISTINCT booking_id) n FROM instructor_hours WHERE instructor_id=? AND lesson_date BETWEEN ? AND ?",(u["id"],month_start.isoformat(),month_end.isoformat())).fetchone()["n"] or 0)

    total_no_show=int(con.execute("""
      SELECT COUNT(*) n FROM bookings b JOIN slots sl ON sl.id=b.slot_id
      WHERE sl.instructor_id=? AND b.status='no_show'
    """,(u["id"],)).fetchone()["n"] or 0)
    day_no_show=int(con.execute("""
      SELECT COUNT(*) n FROM bookings b JOIN slots sl ON sl.id=b.slot_id
      WHERE sl.instructor_id=? AND sl.lesson_date=? AND b.status='no_show'
    """,(u["id"],today.isoformat())).fetchone()["n"] or 0)
    week_no_show=int(con.execute("""
      SELECT COUNT(*) n FROM bookings b JOIN slots sl ON sl.id=b.slot_id
      WHERE sl.instructor_id=? AND sl.lesson_date BETWEEN ? AND ? AND b.status='no_show'
    """,(u["id"],week_start.isoformat(),week_end.isoformat())).fetchone()["n"] or 0)
    month_no_show=int(con.execute("""
      SELECT COUNT(*) n FROM bookings b JOIN slots sl ON sl.id=b.slot_id
      WHERE sl.instructor_id=? AND sl.lesson_date BETWEEN ? AND ? AND b.status='no_show'
    """,(u["id"],month_start.isoformat(),month_end.isoformat())).fetchone()["n"] or 0)

    rows=con.execute("""
      SELECT b.*,sl.lesson_date,sl.start_time,su.name student,su.surname student_surname,
             su.profile_photo student_photo,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) AS level,
             COALESCE(day_sp.name,slot_sp.name) spot,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM bookings b JOIN slots sl ON sl.id=b.slot_id JOIN users su ON su.id=b.student_id
      LEFT JOIN students st ON st.user_id=su.id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE sl.instructor_id=? AND b.status NOT LIKE 'cancelled%'
      ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(u["id"],)).fetchall()
    upcoming=[]; history=[]
    for row in rows:
        item=dict(row)
        try: dt=datetime.strptime(f"{row['lesson_date']} {row['start_time']}","%Y-%m-%d %H:%M")
        except Exception: dt=now_dt
        if row["status"] in ("completed","no_show"): history.append(item)
        elif dt>=now_dt: upcoming.append(item)

    # List the nearest upcoming lesson first; leave history newest-first.
    upcoming.sort(key=lambda b: (b["lesson_date"], b["start_time"], b["id"]))
    rate=float(inst["hourly_rate"] or 0)
    total_pay=total_hours*rate; day_pay=day_hours*rate; week_pay=week_hours*rate; month_pay=month_hours*rate
    con.close()
    return render_template(
      "instructor_profile.html",instructor=inst,total_hours=total_hours,day_hours=day_hours,
      week_hours=week_hours,month_hours=month_hours,completed_lessons=completed_lessons,
      day_lessons=day_lessons,week_lessons=week_lessons,month_lessons=month_lessons,
      total_no_show=total_no_show,day_no_show=day_no_show,week_no_show=week_no_show,month_no_show=month_no_show,
      total_pay=total_pay,day_pay=day_pay,week_pay=week_pay,month_pay=month_pay,
      week_start=week_start.isoformat(),week_end=week_end.isoformat(),upcoming=upcoming,history=history
    )


@app.route("/instructor/students")
def instructor_students():
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))
    q=request.args.get("q","").strip()
    con=db()
    params=[u["id"]]
    where=""
    if q:
        where=" AND (lower(su.name) LIKE lower(?) OR lower(COALESCE(su.surname,'')) LIKE lower(?) OR lower(su.email) LIKE lower(?) OR lower(COALESCE(su.phone,'')) LIKE lower(?))"
        like=f"%{q}%"; params += [like,like,like,like]
    rows=con.execute(f"""
      SELECT su.id,su.name,su.surname,su.email,su.phone,su.profile_photo,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) AS level,st.credits,st.student_code,
             COUNT(DISTINCT b.id) lessons,
             COALESCE(SUM(CASE WHEN COALESCE(bp.attendance_status,b.status)='completed' THEN b.duration ELSE 0 END),0) completed_hours,
             MAX(sl.lesson_date) last_lesson
      FROM bookings b
      JOIN booking_participants bp ON bp.booking_id=b.id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN users su ON su.id=bp.student_id
      LEFT JOIN students st ON st.user_id=su.id
      WHERE sl.instructor_id=? AND b.status NOT LIKE 'cancelled%' {where}
      GROUP BY su.id,su.name,su.surname,su.email,su.phone,su.profile_photo,st.credits,st.student_code
      ORDER BY su.name,su.surname
    """,tuple(params)).fetchall()
    rows=students_with_progress_levels(con, rows)
    con.close()
    return render_template("instructor_students.html",students=rows,q=q)


@app.route("/instructor/students/<int:student_id>")
def instructor_student_detail(student_id):
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))
    con=db()
    allowed=con.execute("""
      SELECT 1 FROM bookings b
      JOIN booking_participants bp ON bp.booking_id=b.id
      JOIN slots sl ON sl.id=b.slot_id
      WHERE sl.instructor_id=? AND bp.student_id=? LIMIT 1
    """,(u["id"],student_id)).fetchone()
    if not allowed:
        con.close(); flash("Ο μαθητής δεν βρέθηκε.")
        return redirect(url_for("instructor_students"))
    student=con.execute("""
      SELECT u.id,u.name,u.surname,u.email,u.phone,u.instagram,u.profile_photo,
             s.level,s.credits,s.student_code,s.lesson_type,s.group_id
      FROM users u LEFT JOIN students s ON s.user_id=u.id WHERE u.id=?
    """,(student_id,)).fetchone()
    history=con.execute("""
      SELECT b.*,COALESCE(bp.attendance_status,b.status) participant_status,
             COALESCE(bp.participant_next_skill,b.next_skill) participant_next_skill,
             COALESCE(bp.participant_notes,b.instructor_notes) participant_notes,
             sl.lesson_date,sl.start_time,COALESCE(day_sp.name,slot_sp.name) spot
      FROM bookings b
      JOIN booking_participants bp ON bp.booking_id=b.id
      JOIN slots sl ON sl.id=b.slot_id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE sl.instructor_id=? AND bp.student_id=? AND b.status NOT LIKE 'cancelled%'
      ORDER BY sl.lesson_date DESC,sl.start_time DESC
    """,(u["id"],student_id)).fetchall()
    history=[dict(r, status=(r["participant_status"] or r["status"]),
                  next_skill=(r["participant_next_skill"] or r["next_skill"]),
                  instructor_notes=(r["participant_notes"] or r["instructor_notes"])) for r in history]
    completed_hours=sum(float(r["duration"] or 0) for r in history if r["status"]=="completed")
    no_show_hours=sum(float(r["duration"] or 0) for r in history if r["status"]=="no_show")
    no_show_count=sum(1 for r in history if r["status"]=="no_show")
    makeup_hours=sum(float(r["duration"] or 0) for r in history if r["status"]=="makeup")
    makeup_count=sum(1 for r in history if r["status"]=="makeup")
    group_members=_group_members(con,student_id)
    progress=get_student_progress(con,student_id)
    con.close()
    return render_template(
      "instructor_student_detail.html",student=student,history=history,
      completed_hours=completed_hours,no_show_hours=no_show_hours,no_show_count=no_show_count,
      makeup_hours=makeup_hours,makeup_count=makeup_count,group_members=group_members,progress=progress
    )


@app.post("/instructor/students/<int:student_id>/progress")
def instructor_student_progress(student_id):
    u=current_user()
    if not u or u["role"]!="instructor": return redirect(url_for("login"))
    con=db()
    allowed=con.execute("""
      SELECT 1 FROM bookings b
      JOIN booking_participants bp ON bp.booking_id=b.id
      JOIN slots sl ON sl.id=b.slot_id
      WHERE sl.instructor_id=? AND bp.student_id=? LIMIT 1
    """,(u["id"],student_id)).fetchone()
    if not allowed:
        con.close(); flash("Ο μαθητής δεν βρέθηκε."); return redirect(url_for("instructor_students"))
    try:
        before,after,progress=set_student_skill_progress(con,student_id,request.form.get("skill_key",""),request.form.get("status",""),u["id"])
        con.commit()
        if before!=after and after=="Kiter": flash("Ο μαθητής ολοκλήρωσε και τα 4 Levels και έγινε Kiter.")
        else: flash("Η πρόοδος ενημερώθηκε.")
    except ValueError as e:
        con.rollback(); flash(str(e))
    finally:
        con.close()
    return redirect(url_for("instructor_student_detail",student_id=student_id)+"#progress")


@app.route("/instructor/lesson/<int:booking_id>")
def instructor_lesson(booking_id):
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))
    con=db()
    lesson=con.execute("""
      SELECT b.*,sl.lesson_date,sl.start_time,sl.instructor_id,
             su.id student_id,su.name student,su.surname student_surname,su.phone student_phone,
             su.profile_photo student_photo,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) AS level,
             COALESCE(day_sp.name,slot_sp.name) spot,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM bookings b JOIN slots sl ON sl.id=b.slot_id
      JOIN users su ON su.id=b.student_id LEFT JOIN students st ON st.user_id=su.id
      JOIN spots slot_sp ON slot_sp.id=sl.spot_id
      LEFT JOIN day_spots ds ON ds.lesson_date=sl.lesson_date
      LEFT JOIN spots day_sp ON day_sp.id=ds.spot_id
      WHERE b.id=?
    """,(booking_id,)).fetchone()
    if not lesson or lesson["instructor_id"]!=u["id"]:
        con.close(); flash("Το μάθημα δεν βρέθηκε.")
        return redirect(url_for("instructor"))
    item=dict(lesson)
    try:
        st=datetime.strptime(lesson["start_time"],"%H:%M")
        item["end_time"]=(st+timedelta(hours=float(lesson["duration"] or 1))).strftime("%H:%M")
    except Exception:
        item["end_time"]=lesson["start_time"]
    previous=con.execute("""
      SELECT b.*,sl.lesson_date,sl.start_time
      FROM bookings b
      JOIN booking_participants bp ON bp.booking_id=b.id
      JOIN slots sl ON sl.id=b.slot_id
      WHERE sl.instructor_id=? AND bp.student_id=? AND COALESCE(bp.attendance_status,b.status)='completed' AND b.id<>?
      ORDER BY sl.lesson_date DESC,sl.start_time DESC LIMIT 6
    """,(u["id"],lesson["student_id"],booking_id)).fetchall()
    participants=_booking_participants(con,booking_id)
    audit_history=get_booking_audit(con,booking_id,20)
    con.close()
    return render_template("instructor_lesson.html",lesson=item,previous=previous,participants=participants,audit_history=audit_history)


@app.route("/instructor/lesson/<int:booking_id>/complete")
def instructor_complete_lesson(booking_id):
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))
    con=db()
    lesson=con.execute("""
      SELECT b.*,sl.lesson_date,sl.start_time,sl.instructor_id,
             su.name student,su.surname student_surname,su.profile_photo student_photo,(CASE WHEN (SELECT COUNT(DISTINCT spp.skill_key) FROM student_skill_progress spp WHERE spp.student_id=su.id AND spp.status='mastered' AND spp.skill_key IN ('l1_theory','l1_trim','l1_control','l1_quick_release','l1_power_strike','l1_bodydrag','l2_control','l2_water_relaunch','l2_bodydrag','l2_self_rescue','l3_control','l3_bodydrag_downwind','l3_bodydrag_upwind','l3_bodydrag_board','l4_bodydrag','l4_waterstart','l4_keep_going','l4_upwind')) = 18 THEN 'Kiter' ELSE 'Beginner' END) AS level,
             (SELECT COUNT(*) FROM booking_participants bp2 WHERE bp2.booking_id=b.id) participant_count,
             (SELECT GROUP_CONCAT(TRIM(pu.name || ' ' || COALESCE(pu.surname,'')), ' · ')
                FROM booking_participants bp3 JOIN users pu ON pu.id=bp3.student_id
               WHERE bp3.booking_id=b.id) participant_names
      FROM bookings b JOIN slots sl ON sl.id=b.slot_id
      JOIN users su ON su.id=b.student_id LEFT JOIN students st ON st.user_id=su.id
      WHERE b.id=?
    """,(booking_id,)).fetchone()
    skills=con.execute("SELECT * FROM skills ORDER BY id").fetchall()
    participants=_booking_participants(con,booking_id) if lesson else []
    progress=get_student_progress(con,lesson["student_id"]) if lesson else None
    participant_progress={}
    for person in participants:
        participant_progress[int(person["student_id"])]=get_student_progress(con,int(person["student_id"]))
    con.close()
    if not lesson or lesson["instructor_id"]!=u["id"]:
        flash("Το μάθημα δεν βρέθηκε.")
        return redirect(url_for("instructor"))
    return render_template(
      "instructor_complete.html",lesson=lesson,skills=skills,participants=participants,
      progress=progress,participant_progress=participant_progress,beginner_curriculum=BEGINNER_CURRICULUM
    )


@app.post("/instructor/no-show/<int:booking_id>")
def instructor_no_show(booking_id):
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))

    con=db(); con.execute("BEGIN IMMEDIATE")
    b=con.execute("""
      SELECT b.*,s.lesson_date,s.start_time,s.instructor_id
      FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.id=?
    """,(booking_id,)).fetchone()
    if not b or b["instructor_id"]!=u["id"]:
        con.rollback(); con.close(); flash("Η κράτηση δεν βρέθηκε.")
        return redirect(url_for("instructor"))

    participants=_booking_participants(con,booking_id)
    if len(participants)>1:
        con.rollback(); con.close()
        flash("Στα group μαθήματα δήλωσε ξεχωριστά Completed / Make-up / No-show για κάθε μαθητή.")
        return redirect(url_for("instructor_complete_lesson",booking_id=booking_id))
    if b["status"]=="no_show":
        con.rollback(); con.close(); flash("Το μάθημα έχει ήδη σημειωθεί ως No-show.")
        return redirect(url_for("instructor_lesson",booking_id=booking_id))
    if b["status"]!="confirmed":
        con.rollback(); con.close(); flash("Μόνο επιβεβαιωμένο μάθημα μπορεί να σημειωθεί ως No-show.")
        return redirect(url_for("instructor_lesson",booking_id=booking_id))

    now=datetime.now().isoformat()
    con.execute("UPDATE bookings SET status='no_show',no_show_at=? WHERE id=?",(now,booking_id))
    con.execute("""
      UPDATE booking_participants SET attendance_status='no_show',attendance_at=?,participant_next_skill=NULL
      WHERE booking_id=?
    """,(now,booking_id))
    for r in con.execute("SELECT slot_id FROM booking_slots WHERE booking_id=?",(booking_id,)).fetchall():
        con.execute("UPDATE slots SET status='booked' WHERE id=?",(r["slot_id"],))
    lesson_date=b["lesson_date"]
    log_booking_audit(con,booking_id,"attendance","Ο instructor σημείωσε No-show.",u["id"],u["role"],"")
    con.commit(); con.close(); rebalance_instructors(lesson_date)
    flash("Το μάθημα σημειώθηκε ως No-show. Οι ώρες χρεώθηκαν κανονικά και δεν επιστράφηκαν στον μαθητή.")
    return redirect(url_for("instructor_lesson",booking_id=booking_id))


@app.post("/instructor/group-complete/<int:booking_id>")
def complete_group(booking_id):
    u=current_user()
    if not u or u["role"]!="instructor":
        return redirect(url_for("login"))

    con=db(); con.execute("BEGIN IMMEDIATE")
    b=con.execute("""
      SELECT b.*,s.lesson_date,s.start_time,s.instructor_id
      FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.id=?
    """,(booking_id,)).fetchone()
    if not b or b["instructor_id"]!=u["id"]:
        con.rollback(); con.close(); flash("Η κράτηση δεν βρέθηκε.")
        return redirect(url_for("instructor"))
    participants=_booking_participants(con,booking_id)
    if len(participants)<=1:
        con.rollback(); con.close(); flash("Αυτή δεν είναι group κράτηση.")
        return redirect(url_for("instructor_complete_lesson",booking_id=booking_id))
    if b["status"] not in ("confirmed","pending_payment"):
        con.rollback(); con.close(); flash("Το group μάθημα έχει ήδη κλείσει.")
        return redirect(url_for("instructor_lesson",booking_id=booking_id))

    valid={"completed","makeup","no_show"}; now=datetime.now().isoformat(); results=[]; any_completed=False
    for person in participants:
        sid=int(person["student_id"])
        status=(request.form.get(f"status_{sid}") or "").strip().lower()
        if status not in valid:
            con.rollback(); con.close(); flash("Επίλεξε κατάσταση για κάθε μέλος του group.")
            return redirect(url_for("instructor_complete_lesson",booking_id=booking_id))
        skill=(request.form.get(f"skill_{sid}") or "").strip()
        notes=(request.form.get(f"notes_{sid}") or "").strip()
        if status=="completed" and not skill: skill="Water Start"
        if status!="completed": skill=""
        any_completed = any_completed or status=="completed"
        results.append((sid,status,skill,notes,person))

    makeup_refunded=0.0
    for sid,status,skill,notes,person in results:
        con.execute("""
          UPDATE booking_participants
          SET attendance_status=?,attendance_at=?,participant_next_skill=?,participant_notes=?
          WHERE booking_id=? AND student_id=?
        """,(status,now,skill or None,notes or None,booking_id,sid))
        # v52: Make-up does not consume the lesson hour. Return only this member's
        # already-reserved credit/package hour so it can be used later for Private or Group.
        if status=="makeup":
            makeup_refunded += _refund_one_booking_participant(
                con,booking_id,sid,"makeup_refund","Make-up hour returned"
            )

    # The instructor works one shared slot, no matter how many group members attended.
    overall_status="completed" if any_completed else "no_show"
    common_skill=next((skill for _,status,skill,_,_ in results if status=="completed" and skill),None)
    common_notes=" | ".join(f"{person['name']}: {notes}" for _,_,_,notes,person in results if notes) or None
    con.execute("""
      UPDATE bookings SET status=?,completed_at=?,no_show_at=?,next_skill=?,instructor_notes=? WHERE id=?
    """,(overall_status,now if any_completed else None,None if any_completed else now,common_skill,common_notes,booking_id))

    already=con.execute("SELECT id FROM instructor_hours WHERE instructor_id=? AND booking_id=? LIMIT 1",(u["id"],booking_id)).fetchone()
    if any_completed and not already:
        worked=_unlogged_instructor_hours_for_booking(con,u["id"],booking_id)
        if worked>0:
            con.execute("""
              INSERT INTO instructor_hours(instructor_id,booking_id,hours,lesson_date,created_at)
              VALUES(?,?,?,?,?)
            """,(u["id"],booking_id,worked,b["lesson_date"],now))

    mail_jobs=[]
    for sid,status,skill,notes,person in results:
        if status=="completed" and person["email"] and skill:
            sk=con.execute("SELECT * FROM skills WHERE name=?",(skill,)).fetchone()
            if sk: mail_jobs.append((person["email"],person["name"],skill,sk["notes"],sk["video_url"]))
    for r in con.execute("SELECT slot_id FROM booking_slots WHERE booking_id=?",(booking_id,)).fetchall():
        con.execute("UPDATE slots SET status='booked' WHERE id=?",(r["slot_id"],))
    lesson_date=b["lesson_date"]
    detail_items=[f"{sid}:{status}" for sid,status,_,_,_ in results]
    log_booking_audit(con,booking_id,"attendance","Ο instructor ολοκλήρωσε την καταχώρηση παρουσίας group.",u["id"],u["role"],"; ".join(detail_items))
    con.commit(); con.close()

    for email,name,skill,skill_notes,video_url in mail_jobs:
        send_email(email,f"KiteClub — Επόμενο βήμα: {skill}",
                   f"Μπράβο {name} για το σημερινό μάθημα.\n\nΕπόμενη τεχνική: {skill}\n{skill_notes}\nVideo: {video_url}\n\nΤα λέμε στο επόμενο μάθημα!")
    rebalance_instructors(lesson_date)
    c=sum(1 for _,status,_,_,_ in results if status=="completed")
    m=sum(1 for _,status,_,_,_ in results if status=="makeup")
    n=sum(1 for _,status,_,_,_ in results if status=="no_show")
    refund_note=f" · επιστράφηκαν {makeup_refunded:g}h" if makeup_refunded else ""
    flash(f"Το group μάθημα καταχωρήθηκε: {c} Completed · {m} Make-up · {n} No-show{refund_note}.")
    return redirect(url_for("instructor_lesson",booking_id=booking_id))


@app.post("/instructor/complete/<int:booking_id>")
def complete(booking_id):
    u=current_user()
    if not u or u["role"]!="instructor": return redirect(url_for("login"))
    worked_keys=[k for k in request.form.getlist("worked_skill") if k in BEGINNER_SKILL_LOOKUP]
    instructor_notes=request.form.get("instructor_notes","").strip(); con=db()
    b=con.execute("""
      SELECT b.*,su.email,su.name,s.lesson_date,s.start_time,s.instructor_id
      FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN users su ON su.id=b.student_id WHERE b.id=?
    """,(booking_id,)).fetchone()
    if not b or b["instructor_id"]!=u["id"]:
        con.close(); flash("Η κράτηση δεν βρέθηκε."); return redirect(url_for("instructor"))
    participants=_booking_participants(con,booking_id)
    if len(participants)>1:
        con.close(); flash("Στο group μάθημα ολοκλήρωσε κάθε μαθητή ξεχωριστά.")
        return redirect(url_for("instructor_complete_lesson",booking_id=booking_id))
    lesson_date=b["lesson_date"]
    if b["status"]=="completed":
        con.close(); flash("Το μάθημα έχει ήδη ολοκληρωθεί."); return redirect(url_for("instructor",date=lesson_date))
    if b["status"]!="confirmed":
        con.close(); flash("Μόνο επιβεβαιωμένο μάθημα μπορεί να ολοκληρωθεί."); return redirect(url_for("instructor",date=lesson_date))

    if not worked_keys:
        con.close(); flash("Επίλεξε τουλάχιστον μία τεχνική που δουλέψατε σήμερα.")
        return redirect(url_for("instructor_complete_lesson",booking_id=booking_id))
    progress_changes=[]
    for skill_key in worked_keys:
        status=(request.form.get(f"progress_status_{skill_key}") or "practicing").strip().lower()
        if status not in ("practicing","mastered"): status="practicing"
        before,after,_=set_student_skill_progress(con,b["student_id"],skill_key,status,u["id"])
        progress_changes.append((skill_key,status,before,after))
    skill=BEGINNER_SKILL_LOOKUP[worked_keys[0]]
    now=datetime.now().isoformat()
    con.execute("UPDATE bookings SET status='completed',completed_at=?,next_skill=?,instructor_notes=? WHERE id=?",(now,skill,instructor_notes,booking_id))
    con.execute("""
      UPDATE booking_participants
      SET attendance_status='completed',attendance_at=?,participant_next_skill=?,participant_notes=? WHERE booking_id=?
    """,(now,skill,instructor_notes or None,booking_id))
    already=con.execute("SELECT id FROM instructor_hours WHERE instructor_id=? AND booking_id=? LIMIT 1",(u["id"],booking_id)).fetchone()
    if not already:
        worked=_unlogged_instructor_hours_for_booking(con,u["id"],booking_id)
        if worked>0:
            con.execute("INSERT INTO instructor_hours(instructor_id,booking_id,hours,lesson_date,created_at) VALUES(?,?,?,?,?)",(u["id"],booking_id,worked,lesson_date,now))
    sk=con.execute("SELECT * FROM skills WHERE name=?",(skill,)).fetchone(); participants=_booking_participants(con,booking_id); log_booking_audit(con,booking_id,"attendance","Ο instructor ολοκλήρωσε το μάθημα.",u["id"],u["role"],f"next_skill={skill}; worked={','.join(worked_keys)}"); con.commit(); con.close()
    if sk:
        for person in participants:
            if person["email"]:
                send_email(person["email"],f"KiteClub — Επόμενο βήμα: {skill}",f"Μπράβο {person['name']} για το σημερινό μάθημα.\n\nΕπόμενη τεχνική: {skill}\n{sk['notes']}\nVideo: {sk['video_url']}\n\nΤα λέμε στο επόμενο μάθημα!")
    became_kiter=any(before!=after and after=="Kiter" for _,_,before,after in progress_changes)
    if became_kiter:
        flash("Το μάθημα ολοκληρώθηκε, η πρόοδος ενημερώθηκε και ο μαθητής έγινε Kiter!")
    else:
        flash("Το μάθημα ολοκληρώθηκε, οι ώρες και η πρόοδος καταγράφηκαν.")
    return redirect(url_for("instructor_lesson",booking_id=booking_id))


init_db()

if __name__=="__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true", "yes"),
    )
