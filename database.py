import sqlite3
import qrcode
import os
from datetime import datetime, date

DB_PATH = "scms.db"


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "scms.db")
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def connect_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        class TEXT,
        email TEXT,
        phone TEXT,
        user_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        date TEXT,
        status TEXT DEFAULT 'Present',
        marked_by TEXT DEFAULT 'manual',
        time TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class TEXT,
        day TEXT,
        period INTEGER,
        subject TEXT,
        teacher TEXT,
        time_start TEXT,
        time_end TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        code TEXT,
        teacher TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        body TEXT,
        author TEXT,
        target TEXT DEFAULT 'all',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        pinned INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        type TEXT DEFAULT 'info',
        read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    os.makedirs("qrcodes", exist_ok=True)
    os.makedirs("credentials", exist_ok=True)

    # Default users
    for uname, pwd, role in [("admin", "admin123", "admin"), ("teacher", "teacher123", "teacher")]:
        c.execute("SELECT id FROM users WHERE username=?", (uname,))
        if not c.fetchone():
            c.execute("INSERT INTO users VALUES (NULL,?,?,?)", (uname, pwd, role))

    # Seed timetable
    c.execute("SELECT COUNT(*) FROM timetable")
    if c.fetchone()[0] == 0:
        sample = [
            ("10A","Monday",1,"Mathematics","Mr. Sharma","09:00","09:45"),
            ("10A","Monday",2,"Physics","Ms. Patel","09:45","10:30"),
            ("10A","Monday",3,"Chemistry","Mr. Khan","10:45","11:30"),
            ("10A","Monday",4,"English","Ms. Reddy","11:30","12:15"),
            ("10A","Tuesday",1,"Biology","Dr. Mehta","09:00","09:45"),
            ("10A","Tuesday",2,"Mathematics","Mr. Sharma","09:45","10:30"),
            ("10A","Tuesday",3,"Computer Science","Mr. Iyer","10:45","11:30"),
            ("10A","Tuesday",4,"History","Ms. Nair","11:30","12:15"),
            ("10A","Wednesday",1,"Physics","Ms. Patel","09:00","09:45"),
            ("10A","Wednesday",2,"Chemistry","Mr. Khan","09:45","10:30"),
            ("10A","Wednesday",3,"English","Ms. Reddy","10:45","11:30"),
            ("10A","Wednesday",4,"Mathematics","Mr. Sharma","11:30","12:15"),
            ("10A","Thursday",1,"Computer Science","Mr. Iyer","09:00","09:45"),
            ("10A","Thursday",2,"Biology","Dr. Mehta","09:45","10:30"),
            ("10A","Thursday",3,"Mathematics","Mr. Sharma","10:45","11:30"),
            ("10A","Thursday",4,"Physics","Ms. Patel","11:30","12:15"),
            ("10A","Friday",1,"History","Ms. Nair","09:00","09:45"),
            ("10A","Friday",2,"English","Ms. Reddy","09:45","10:30"),
            ("10A","Friday",3,"Chemistry","Mr. Khan","10:45","11:30"),
            ("10A","Friday",4,"Biology","Dr. Mehta","11:30","12:15"),
        ]
        c.executemany("INSERT INTO timetable VALUES (NULL,?,?,?,?,?,?,?)", sample)

    conn.commit()
    conn.close()


def login_user(username, password):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, role, username FROM users WHERE username=? AND password=?", (username, password))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def add_student(name, cls, email="", phone=""):
    conn = get_db()
    c = conn.cursor()
    username = name.lower().replace(" ", "") + datetime.now().strftime("%H%M%S")
    password = "1234"
    try:
        c.execute("INSERT INTO users VALUES (NULL,?,?,?)", (username, password, "student"))
        user_id = c.lastrowid
        c.execute("INSERT INTO students VALUES (NULL,?,?,?,?,?,CURRENT_TIMESTAMP)", (name, cls, email, phone, user_id))
        student_id = c.lastrowid
        conn.commit()
        generate_qr(student_id)
        with open(f"credentials/{username}.txt", "w") as f:
            f.write(f"Username: {username}\nPassword: {password}")
        return student_id, username, password
    except Exception as e:
        conn.rollback()
        return None, None, None
    finally:
        conn.close()


def generate_qr(student_id):
    img = qrcode.make(str(student_id))
    img.save(f"qrcodes/student_{student_id}.png")


def get_students(cls_filter=None):
    conn = get_db()
    c = conn.cursor()
    if cls_filter:
        c.execute("SELECT * FROM students WHERE class=? ORDER BY name", (cls_filter,))
    else:
        c.execute("SELECT * FROM students ORDER BY class, name")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def delete_student(student_id):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM students WHERE id=?", (student_id,))
        res = c.fetchone()
        if res:
            c.execute("DELETE FROM attendance WHERE student_id=?", (student_id,))
            c.execute("DELETE FROM students WHERE id=?", (student_id,))
            c.execute("DELETE FROM users WHERE id=?", (res["user_id"],))
            conn.commit()
    except Exception as e:
        conn.rollback()
    finally:
        conn.close()
    qr = f"qrcodes/student_{student_id}.png"
    if os.path.exists(qr):
        os.remove(qr)


def mark_attendance(student_id, status="Present", marked_by="manual"):
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M:%S")
    c.execute("SELECT id FROM attendance WHERE student_id=? AND date=?", (student_id, today))
    existing = c.fetchone()
    if existing:
        c.execute("UPDATE attendance SET status=?, time=? WHERE student_id=? AND date=?",
                  (status, now, student_id, today))
    else:
        c.execute("INSERT INTO attendance VALUES (NULL,?,?,?,?,?)", (student_id, today, status, marked_by, now))
    conn.commit()
    conn.close()
    return True


def get_today_attendance():
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()
    c.execute("""
        SELECT s.id, s.name, s.class,
               COALESCE(a.status, 'Absent') as status,
               COALESCE(a.time, '') as time,
               COALESCE(a.marked_by, '') as marked_by
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id AND a.date=?
        ORDER BY s.class, s.name
    """, (today,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_dashboard_stats():
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()

    c.execute("SELECT COUNT(*) as n FROM students")
    total = c.fetchone()["n"]

    c.execute("SELECT COUNT(*) as n FROM attendance WHERE date=? AND status='Present'", (today,))
    present = c.fetchone()["n"]

    absent = total - present
    pct = round((present / total * 100) if total else 0, 1)

    # Weekly data (last 7 days)
    c.execute("""
        SELECT date, COUNT(*) as cnt
        FROM attendance
        WHERE status='Present'
        GROUP BY date
        ORDER BY date DESC
        LIMIT 7
    """)
    weekly = [dict(r) for r in c.fetchall()]

    # Class-wise
    c.execute("""
        SELECT s.class,
               COUNT(DISTINCT s.id) as total,
               COUNT(DISTINCT CASE WHEN a.status='Present' AND a.date=? THEN s.id END) as present
        FROM students s
        LEFT JOIN attendance a ON s.id=a.student_id
        GROUP BY s.class
    """, (today,))
    class_stats = [dict(r) for r in c.fetchall()]

    # Recent activity
    c.execute("""
        SELECT s.name, s.class, a.time, a.status, a.marked_by, a.date
        FROM attendance a
        JOIN students s ON a.student_id=s.id
        ORDER BY a.date DESC, a.time DESC
        LIMIT 10
    """)
    recent = [dict(r) for r in c.fetchall()]

    conn.close()
    return {
        "total": total,
        "present": present,
        "absent": absent,
        "percentage": pct,
        "weekly": list(reversed(weekly)),
        "class_stats": class_stats,
        "recent": recent
    }


def get_attendance_report(student_id=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT date) as d FROM attendance")
    total_days = c.fetchone()["d"] or 1

    if student_id:
        c.execute("""
            SELECT s.id, s.name, s.class,
                   COUNT(CASE WHEN a.status='Present' THEN 1 END) as attended,
                   COUNT(CASE WHEN a.status='Absent' THEN 1 END) as absent_count
            FROM students s
            LEFT JOIN attendance a ON s.id=a.student_id
            WHERE s.id=?
            GROUP BY s.id
        """, (student_id,))
    else:
        c.execute("""
            SELECT s.id, s.name, s.class,
                   COUNT(CASE WHEN a.status='Present' THEN 1 END) as attended,
                   COUNT(CASE WHEN a.status='Absent' THEN 1 END) as absent_count
            FROM students s
            LEFT JOIN attendance a ON s.id=a.student_id
            GROUP BY s.id
            ORDER BY s.class, s.name
        """)

    rows = []
    for r in c.fetchall():
        d = dict(r)
        d["total_days"] = total_days
        d["percentage"] = round((d["attended"] / total_days * 100), 1)
        rows.append(d)

    conn.close()
    return rows


def get_student_by_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_timetable(cls=None):
    conn = get_db()
    c = conn.cursor()
    days = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
    if cls:
        c.execute("SELECT * FROM timetable WHERE class=? ORDER BY day, period", (cls,))
    else:
        c.execute("SELECT * FROM timetable ORDER BY class, day, period")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_classes():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT class FROM students ORDER BY class")
    rows = [r["class"] for r in c.fetchall()]
    c.execute("SELECT DISTINCT class FROM timetable ORDER BY class")
    tt_cls = [r["class"] for r in c.fetchall()]
    conn.close()
    return list(set(rows + tt_cls))


def add_timetable_entry(cls, day, period, subject, teacher, time_start, time_end):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM timetable WHERE class=? AND day=? AND period=?", (cls, day, period))
    c.execute("INSERT INTO timetable VALUES (NULL,?,?,?,?,?,?,?)",
              (cls, day, period, subject, teacher, time_start, time_end))
    conn.commit()
    conn.close()


def delete_timetable_entry(entry_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM timetable WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()


def get_student_attendance_history(student_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT date, status, time FROM attendance
                 WHERE student_id=? ORDER BY date DESC LIMIT 30""", (student_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ─── Announcements ────────────────────────────────────────────────────────────
def get_announcements(target=None):
    conn = get_db()
    c = conn.cursor()
    if target:
        c.execute("""SELECT * FROM announcements
                     WHERE target='all' OR target=?
                     ORDER BY pinned DESC, created_at DESC""", (target,))
    else:
        c.execute("SELECT * FROM announcements ORDER BY pinned DESC, created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_announcement(title, body, author, target='all', pinned=0):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO announcements VALUES (NULL,?,?,?,?,CURRENT_TIMESTAMP,?)",
              (title, body, author, target, pinned))
    ann_id = c.lastrowid
    conn.commit()
    conn.close()
    return ann_id

def delete_announcement(ann_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    conn.commit()
    conn.close()

def toggle_pin(ann_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE announcements SET pinned = 1-pinned WHERE id=?", (ann_id,))
    conn.commit()
    conn.close()

# ─── Notifications ────────────────────────────────────────────────────────────
def get_notifications(user_id, unread_only=False):
    conn = get_db()
    c = conn.cursor()
    if unread_only:
        c.execute("SELECT * FROM notifications WHERE user_id=? AND read=0 ORDER BY created_at DESC", (user_id,))
    else:
        c.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_notification(user_id, message, ntype='info'):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO notifications VALUES (NULL,?,?,?,0,CURRENT_TIMESTAMP)", (user_id, message, ntype))
    conn.commit()
    conn.close()

def mark_notifications_read(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def unread_count(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as n FROM notifications WHERE user_id=? AND read=0", (user_id,))
    n = c.fetchone()["n"]
    conn.close()
    return n

# ─── Settings / User ──────────────────────────────────────────────────────────
def change_password(user_id, old_pw, new_pw):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id=? AND password=?", (user_id, old_pw))
    row = c.fetchone()
    if row:
        c.execute("UPDATE users SET password=? WHERE id=?", (new_pw, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_user_by_id(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

# ─── Subjects ─────────────────────────────────────────────────────────────────
def get_subjects():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM subjects ORDER BY name")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_subject(name, code, teacher):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO subjects VALUES (NULL,?,?,?)", (name, code, teacher))
        conn.commit()
    except:
        conn.rollback()
    conn.close()

def delete_subject(sid):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM subjects WHERE id=?", (sid,))
    conn.commit()
    conn.close()

# ─── CSV Export helpers ────────────────────────────────────────────────────────
def get_full_attendance_log(cls_filter=None):
    conn = get_db()
    c = conn.cursor()
    if cls_filter:
        c.execute("""SELECT s.name, s.class, a.date, a.status, a.time, a.marked_by
                     FROM attendance a JOIN students s ON a.student_id=s.id
                     WHERE s.class=? ORDER BY a.date DESC, s.name""", (cls_filter,))
    else:
        c.execute("""SELECT s.name, s.class, a.date, a.status, a.time, a.marked_by
                     FROM attendance a JOIN students s ON a.student_id=s.id
                     ORDER BY a.date DESC, s.name""")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_student_by_id(sid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE id=?", (sid,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Email Config (stored in DB) ──────────────────────────────────────────────
def ensure_email_config_table():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS email_config (
        id INTEGER PRIMARY KEY CHECK(id=1),
        smtp_host TEXT DEFAULT '',
        smtp_port INTEGER DEFAULT 587,
        smtp_user TEXT DEFAULT '',
        smtp_pass TEXT DEFAULT '',
        sender_name TEXT DEFAULT 'SCMS Pro',
        enabled INTEGER DEFAULT 0
    )""")
    c.execute("SELECT id FROM email_config WHERE id=1")
    if not c.fetchone():
        c.execute("INSERT INTO email_config VALUES (1,'',587,'','','SCMS Pro',0)")
    conn.commit()
    conn.close()

def get_email_config():
    ensure_email_config_table()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM email_config WHERE id=1")
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}

def save_email_config(host, port, user, pwd, sender_name, enabled):
    ensure_email_config_table()
    conn = get_db()
    c = conn.cursor()
    c.execute("""UPDATE email_config SET smtp_host=?,smtp_port=?,smtp_user=?,
                 smtp_pass=?,sender_name=?,enabled=? WHERE id=1""",
              (host, int(port), user, pwd, sender_name, int(enabled)))
    conn.commit()
    conn.close()

def get_student_with_user(student_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT s.*, u.username, u.password as raw_password
                 FROM students s JOIN users u ON s.user_id=u.id
                 WHERE s.id=?""", (student_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_students_with_credentials():
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT s.*, u.username, u.password as raw_password
                 FROM students s JOIN users u ON s.user_id=u.id
                 WHERE s.email IS NOT NULL AND s.email != ''
                 ORDER BY s.class, s.name""")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def log_email_sent(student_id, to_email, status, error=''):
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        to_email TEXT,
        status TEXT,
        error TEXT,
        sent_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("INSERT INTO email_log VALUES (NULL,?,?,?,?,CURRENT_TIMESTAMP)",
              (student_id, to_email, status, error))
    conn.commit()
    conn.close()

def get_email_log(limit=50):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""SELECT el.*, s.name, s.class
                     FROM email_log el
                     JOIN students s ON el.student_id=s.id
                     ORDER BY el.sent_at DESC LIMIT ?""", (limit,))
        rows = [dict(r) for r in c.fetchall()]
    except:
        rows = []
    conn.close()
    return rows


def get_student_credentials(student_id):
    """Get username and password for a student by their student ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT u.username, u.password
                 FROM users u
                 JOIN students s ON s.user_id = u.id
                 WHERE s.id = ?""", (student_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_student_with_user(student_id):
    """Return student data including username and password for emailing."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT s.*, u.username, u.password as raw_password, u.id as user_id
                 FROM students s JOIN users u ON s.user_id = u.id
                 WHERE s.id = ?""", (student_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_students_with_credentials():
    """Return all students who have an email with their login credentials."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT s.*, u.username, u.password as raw_password, u.id as user_id
                 FROM students s JOIN users u ON s.user_id = u.id
                 WHERE s.email IS NOT NULL AND s.email != ''
                 ORDER BY s.class, s.name""")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
