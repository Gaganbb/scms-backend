from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, Response, send_file)
import json
import time
import queue
import threading
import os
from datetime import date, datetime
from database import *
from mailer import send_credentials_email, test_smtp_connection

app = Flask(__name__)
app.secret_key = "scms_secret_2024"

connect_db()

# ─── Real-time SSE queue per client ───────────────────────────────────────────
listeners = []
listeners_lock = threading.Lock()

def push_event(data: dict):
    """Push an event to all SSE listeners."""
    msg = f"data: {json.dumps(data)}\n\n"
    with listeners_lock:
        dead = []
        for q in listeners:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            listeners.remove(q)

# ─── Auth helpers ─────────────────────────────────────────────────────────────
def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def admin_or_teacher(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("admin", "teacher"):
            return redirect(url_for("student_portal"))
        return fn(*args, **kwargs)
    return wrapper

# ─── Auth ─────────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        user = login_user(username, password)
        if user:
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["username"] = user["username"]
            if user["role"] in ("admin", "teacher"):
                return redirect(url_for("dashboard"))
            else:
                return redirect(url_for("student_portal"))
        return render_template("login.html", error="Invalid credentials. Please try again.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─── Dashboard ────────────────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
@admin_or_teacher
def dashboard():
    stats = get_dashboard_stats()
    classes = get_classes()
    return render_template("dashboard.html", stats=stats, classes=classes,
                           username=session.get("username"), role=session.get("role"))

@app.route("/api/stats")
@login_required
def api_stats():
    return jsonify(get_dashboard_stats())

# ─── Students ─────────────────────────────────────────────────────────────────
@app.route("/students")
@login_required
@admin_or_teacher
def students():
    cls_filter = request.args.get("class", "")
    all_students = get_students(cls_filter if cls_filter else None)
    classes = get_classes()
    return render_template("students.html", students=all_students,
                           classes=classes, cls_filter=cls_filter,
                           username=session.get("username"), role=session.get("role"))

@app.route("/students/add", methods=["POST"])
@login_required
@admin_or_teacher
def add_student_route():
    name  = request.form.get("name","").strip()
    cls   = request.form.get("class","").strip()
    email = request.form.get("email","").strip()
    phone = request.form.get("phone","").strip()
    send_email = request.form.get("send_email","0") == "1"
    if name and cls:
        sid, username, password = add_student(name, cls, email, phone)
        if sid:
            push_event({"type": "student_added", "name": name, "class": cls})
            email_status = None
            email_error  = None
            if send_email and email:
                cfg  = get_email_config()
                base = request.host_url.rstrip("/")
                qr   = f"qrcodes/student_{sid}.png"
                ok, err = send_credentials_email(
                    email, name, cls, username, password, cfg,
                    qr_path=qr, portal_url=base
                )
                email_status = "sent" if ok else "failed"
                email_error  = err
                log_email_sent(sid, email, email_status, err)
            return jsonify({
                "success": True, "student_id": sid,
                "username": username, "password": password,
                "email_status": email_status, "email_error": email_error
            })
    return jsonify({"success": False, "error": "Missing fields"})

@app.route("/students/delete/<int:sid>", methods=["POST"])
@login_required
@admin_or_teacher
def delete_student_route(sid):
    delete_student(sid)
    push_event({"type": "student_deleted", "student_id": sid})
    return jsonify({"success": True})

@app.route("/students/qr/<int:sid>")
@login_required
def get_qr(sid):
    path = f"qrcodes/student_{sid}.png"
    if os.path.exists(path):
        return send_file(path, mimetype="image/png")
    return "QR not found", 404

# ─── Attendance ───────────────────────────────────────────────────────────────
@app.route("/attendance")
@login_required
@admin_or_teacher
def attendance():
    cls_filter = request.args.get("class", "")
    today_data = get_today_attendance()
    if cls_filter:
        today_data = [s for s in today_data if s["class"] == cls_filter]
    classes = get_classes()
    report = get_attendance_report()
    today = date.today().strftime("%A, %d %B %Y")
    return render_template("attendance.html",
                           today_data=today_data, classes=classes,
                           cls_filter=cls_filter, report=report, today=today,
                           username=session.get("username"), role=session.get("role"))

@app.route("/attendance/mark", methods=["POST"])
@login_required
@admin_or_teacher
def mark_attendance_route():
    data = request.get_json()
    student_id = data.get("student_id")
    status = data.get("status", "Present")
    if student_id:
        mark_attendance(student_id, status, marked_by=session.get("username","manual"))
        # Get student name for event
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT name, class FROM students WHERE id=?", (student_id,))
        row = c.fetchone()
        conn.close()
        if row:
            push_event({
                "type": "attendance_marked",
                "student_id": student_id,
                "name": row["name"],
                "class": row["class"],
                "status": status,
                "time": datetime.now().strftime("%H:%M:%S")
            })
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/attendance/mark-all", methods=["POST"])
@login_required
@admin_or_teacher
def mark_all_present():
    data = request.get_json()
    cls = data.get("class", "")
    students_list = get_students(cls if cls else None)
    for s in students_list:
        mark_attendance(s["id"], "Present", marked_by=session.get("username","manual"))
    push_event({"type": "bulk_attendance", "class": cls, "count": len(students_list)})
    return jsonify({"success": True, "count": len(students_list)})

@app.route("/api/today-attendance")
@login_required
def api_today_attendance():
    cls_filter = request.args.get("class", "")
    data = get_today_attendance()
    if cls_filter:
        data = [s for s in data if s["class"] == cls_filter]
    return jsonify(data)

# ─── Timetable ────────────────────────────────────────────────────────────────
@app.route("/timetable")
@login_required
@admin_or_teacher
def timetable():
    cls = request.args.get("class", "10A")
    tt = get_timetable(cls)
    classes = get_classes()
    # Organize into grid
    days = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
    periods = list(range(1, 9))
    grid = {d: {p: None for p in periods} for d in days}
    for entry in tt:
        if entry["day"] in grid and entry["period"] in grid[entry["day"]]:
            grid[entry["day"]][entry["period"]] = entry
    return render_template("timetable.html", grid=grid, days=days,
                           periods=periods, classes=classes, selected_class=cls,
                           username=session.get("username"), role=session.get("role"))

@app.route("/timetable/add", methods=["POST"])
@login_required
@admin_or_teacher
def add_timetable():
    d = request.get_json()
    add_timetable_entry(d["class"], d["day"], int(d["period"]),
                        d["subject"], d["teacher"], d["time_start"], d["time_end"])
    return jsonify({"success": True})

@app.route("/timetable/delete/<int:eid>", methods=["POST"])
@login_required
@admin_or_teacher
def delete_timetable(eid):
    delete_timetable_entry(eid)
    return jsonify({"success": True})

# ─── Reports ──────────────────────────────────────────────────────────────────
@app.route("/reports")
@login_required
@admin_or_teacher
def reports():
    report = get_attendance_report()
    classes = get_classes()
    return render_template("reports.html", report=report, classes=classes,
                           username=session.get("username"), role=session.get("role"))

# ─── Student Portal ───────────────────────────────────────────────────────────
@app.route("/portal")
@login_required
def student_portal():
    if session.get("role") in ("admin", "teacher"):
        return redirect(url_for("dashboard"))
    student = get_student_by_user(session["user_id"])
    if not student:
        return "Student not found", 404
    report = get_attendance_report(student["id"])
    history = get_student_attendance_history(student["id"])
    tt = get_timetable(student["class"])
    days = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
    periods = list(range(1, 9))
    grid = {d: {p: None for p in periods} for d in days}
    for entry in tt:
        if entry["day"] in grid:
            grid[entry["day"]][entry["period"]] = entry
    today_day = datetime.now().strftime("%A")
    return render_template("student_portal.html",
                           student=student,
                           report=report[0] if report else {},
                           history=history,
                           grid=grid, days=days, periods=periods,
                           today_day=today_day,
                           username=session.get("username"))

# ─── SSE Stream ───────────────────────────────────────────────────────────────
@app.route("/stream")
@login_required
def stream():
    q = queue.Queue(maxsize=20)
    with listeners_lock:
        listeners.append(q)

    def generate():
        yield "data: {\"type\": \"connected\"}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield msg
                except queue.Empty:
                    yield ": ping\n\n"  # keep-alive
        except GeneratorExit:
            with listeners_lock:
                if q in listeners:
                    listeners.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})

# ─── Announcements ────────────────────────────────────────────────────────────
@app.route("/announcements")
@login_required
def announcements():
    target = session.get("role", "all")
    anns = get_announcements(target)
    return render_template("announcements.html", announcements=anns,
                           username=session.get("username"), role=session.get("role"))

@app.route("/announcements/add", methods=["POST"])
@login_required
@admin_or_teacher
def add_announcement_route():
    d = request.get_json()
    aid = add_announcement(
        d.get("title","").strip(),
        d.get("body","").strip(),
        session.get("username"),
        d.get("target","all"),
        int(d.get("pinned", 0))
    )
    # Notify all users
    push_event({"type": "new_announcement", "title": d.get("title"), "id": aid})
    return jsonify({"success": True, "id": aid})

@app.route("/announcements/delete/<int:aid>", methods=["POST"])
@login_required
@admin_or_teacher
def delete_ann(aid):
    delete_announcement(aid)
    return jsonify({"success": True})

@app.route("/announcements/pin/<int:aid>", methods=["POST"])
@login_required
@admin_or_teacher
def pin_ann(aid):
    toggle_pin(aid)
    return jsonify({"success": True})

# ─── Notifications ────────────────────────────────────────────────────────────
@app.route("/api/notifications")
@login_required
def api_notifications():
    uid  = session["user_id"]
    data = get_notifications(uid)
    cnt  = unread_count(uid)
    return jsonify({"notifications": data, "unread": cnt})

@app.route("/api/notifications/read", methods=["POST"])
@login_required
def read_notifications():
    mark_notifications_read(session["user_id"])
    return jsonify({"success": True})

# ─── Settings ─────────────────────────────────────────────────────────────────
@app.route("/settings")
@login_required
def settings():
    user = get_user_by_id(session["user_id"])
    subjects = get_subjects()
    return render_template("settings.html", user=user, subjects=subjects,
                           username=session.get("username"), role=session.get("role"))

@app.route("/settings/change-password", methods=["POST"])
@login_required
def change_pw():
    d = request.get_json()
    ok = change_password(session["user_id"], d.get("old_pw"), d.get("new_pw"))
    return jsonify({"success": ok, "error": "Wrong current password" if not ok else ""})

@app.route("/settings/subjects/add", methods=["POST"])
@login_required
@admin_or_teacher
def add_subject_route():
    d = request.get_json()
    add_subject(d.get("name",""), d.get("code",""), d.get("teacher",""))
    return jsonify({"success": True})

@app.route("/settings/subjects/delete/<int:sid>", methods=["POST"])
@login_required
@admin_or_teacher
def del_subject_route(sid):
    delete_subject(sid)
    return jsonify({"success": True})

# ─── Export CSV ───────────────────────────────────────────────────────────────
@app.route("/export/attendance")
@login_required
@admin_or_teacher
def export_attendance_csv():
    import csv, io
    cls = request.args.get("class","")
    rows = get_full_attendance_log(cls if cls else None)
    si = io.StringIO()
    w = csv.DictWriter(si, fieldnames=["name","class","date","status","time","marked_by"])
    w.writeheader()
    w.writerows(rows)
    output = io.BytesIO()
    output.write(si.getvalue().encode("utf-8"))
    output.seek(0)
    fname = f"attendance_{cls or 'all'}_{date.today()}.csv"
    return send_file(output, mimetype="text/csv",
                     as_attachment=True, download_name=fname)

@app.route("/export/students")
@login_required
@admin_or_teacher
def export_students_csv():
    import csv, io
    students = get_students()
    report   = {r["id"]: r for r in get_attendance_report()}
    si = io.StringIO()
    w = csv.writer(si)
    w.writerow(["ID","Name","Class","Email","Phone","Attended","Total","Percentage"])
    for s in students:
        r = report.get(s["id"], {})
        w.writerow([s["id"], s["name"], s["class"], s.get("email",""),
                    s.get("phone",""), r.get("attended",0),
                    r.get("total_days",0), r.get("percentage",0)])
    output = io.BytesIO()
    output.write(si.getvalue().encode("utf-8"))
    output.seek(0)
    return send_file(output, mimetype="text/csv",
                     as_attachment=True, download_name=f"students_{date.today()}.csv")

# ─── QR Webcam scan endpoint ─────────────────────────────────────────────────
@app.route("/attendance/scan-qr-page")
@login_required
@admin_or_teacher
def qr_scan_page():
    return render_template("qr_scan.html",
                           username=session.get("username"), role=session.get("role"))

# ─── API: student by ID (for QR lookup) ─────────────────────────────────────
@app.route("/api/student/<int:sid>")
@login_required
def api_student(sid):
    s = get_student_by_id(sid)
    if s:
        return jsonify(s)
    return jsonify({"error": "Not found"}), 404

# ─── Student Detail Page ─────────────────────────────────────────────────────
@app.route("/students/<int:sid>")
@login_required
@admin_or_teacher
def student_detail(sid):
    s = get_student_by_id(sid)
    if not s:
        return redirect(url_for("students"))
    history  = get_student_attendance_history(sid)
    report   = get_attendance_report(sid)
    rep      = report[0] if report else {}
    # Build a 30-day calendar map
    from datetime import timedelta
    cal = {}
    today = date.today()
    for i in range(29, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        cal[d] = "none"
    for h in history:
        if h["date"] in cal:
            cal[h["date"]] = h["status"]
    # streak
    streak = 0
    for d in sorted(cal.keys(), reverse=True):
        if cal[d] == "Present":
            streak += 1
        elif cal[d] == "Absent":
            break
        # "none" = no class, skip
    return render_template("student_detail.html", student=s, history=history,
                           report=rep, cal=cal, streak=streak,
                           username=session.get("username"), role=session.get("role"))

# ─── Bulk CSV Import ──────────────────────────────────────────────────────────
@app.route("/students/import", methods=["GET","POST"])
@login_required
@admin_or_teacher
def import_students():
    if request.method == "GET":
        return render_template("import_students.html",
                               username=session.get("username"), role=session.get("role"))
    import csv, io
    file = request.files.get("csv_file")
    if not file:
        return jsonify({"success": False, "error": "No file uploaded"})
    stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
    reader = csv.DictReader(stream)
    added, skipped = 0, 0
    results = []
    for row in reader:
        name  = (row.get("name","") or row.get("Name","")).strip()
        cls   = (row.get("class","") or row.get("Class","")).strip()
        email = (row.get("email","") or row.get("Email","")).strip()
        phone = (row.get("phone","") or row.get("Phone","")).strip()
        if name and cls:
            sid, uname, pwd = add_student(name, cls, email, phone)
            if sid:
                added += 1
                results.append({"name": name, "class": cls,
                                 "username": uname, "password": pwd})
                push_event({"type": "student_added", "name": name, "class": cls})
            else:
                skipped += 1
        else:
            skipped += 1
    return jsonify({"success": True, "added": added,
                    "skipped": skipped, "results": results})

# ─── Print Attendance Sheet ────────────────────────────────────────────────────
@app.route("/print/attendance")
@login_required
@admin_or_teacher
def print_attendance():
    cls   = request.args.get("class","")
    today_data = get_today_attendance()
    if cls:
        today_data = [s for s in today_data if s["class"] == cls]
    report = get_attendance_report()
    classes = get_classes()
    today  = date.today().strftime("%A, %d %B %Y")
    return render_template("print_attendance.html",
                           today_data=today_data, report=report,
                           classes=classes, cls_filter=cls, today=today)

# ─── Email Settings ───────────────────────────────────────────────────────────
@app.route("/settings/email", methods=["GET"])
@login_required
@admin_or_teacher
def email_settings():
    cfg     = get_email_config()
    log     = get_email_log()
    classes = get_classes()
    return render_template("email_settings.html",
                           cfg=cfg, log=log, classes=classes,
                           username=session.get("username"), role=session.get("role"))

@app.route("/settings/email/save", methods=["POST"])
@login_required
@admin_or_teacher
def save_email_cfg():
    d = request.get_json()
    save_email_config(
        d.get("smtp_host",""),
        d.get("smtp_port", 587),
        d.get("smtp_user",""),
        d.get("smtp_pass",""),
        d.get("sender_name","SCMS Pro"),
        int(d.get("enabled", 0))
    )
    return jsonify({"success": True})

@app.route("/settings/email/test", methods=["POST"])
@login_required
@admin_or_teacher
def test_email():
    d   = request.get_json()
    cfg = {
        "smtp_host":   d.get("smtp_host",""),
        "smtp_port":   d.get("smtp_port", 587),
        "smtp_user":   d.get("smtp_user",""),
        "smtp_pass":   d.get("smtp_pass",""),
        "sender_name": d.get("sender_name","SCMS Pro"),
        "enabled":     1
    }
    ok, msg = test_smtp_connection(cfg)
    return jsonify({"success": ok, "message": msg})

@app.route("/email/send/<int:sid>", methods=["POST"])
@login_required
@admin_or_teacher
def send_one_email(sid):
    """Send credentials email to a single student."""
    s = get_student_with_user(sid)
    if not s:
        return jsonify({"success": False, "error": "Student not found"})
    if not s.get("email"):
        return jsonify({"success": False, "error": "Student has no email address"})
    cfg  = get_email_config()
    base = request.host_url.rstrip("/")
    qr   = f"qrcodes/student_{sid}.png"
    ok, err = send_credentials_email(
        s["email"], s["name"], s["class"],
        s["username"], s["raw_password"],
        cfg, qr_path=qr, portal_url=base
    )
    status = "sent" if ok else "failed"
    log_email_sent(sid, s["email"], status, err)
    if ok:
        add_notification(s["user_id"],
                         f"Your login credentials were sent to {s['email']}", "info")
    return jsonify({"success": ok, "error": err})

@app.route("/email/send-bulk", methods=["POST"])
@login_required
@admin_or_teacher
def send_bulk_emails():
    """Send credentials to all students who have an email address."""
    import threading
    data     = request.get_json() or {}
    cls_f    = data.get("class","")
    cfg      = get_email_config()
    base     = request.host_url.rstrip("/")
    students = get_all_students_with_credentials()
    if cls_f:
        students = [s for s in students if s["class"] == cls_f]

    results = {"sent": 0, "failed": 0, "skipped": 0, "details": []}

    def do_send():
        for s in students:
            qr = f"qrcodes/student_{s['id']}.png"
            ok, err = send_credentials_email(
                s["email"], s["name"], s["class"],
                s["username"], s["raw_password"],
                cfg, qr_path=qr, portal_url=base
            )
            status = "sent" if ok else "failed"
            log_email_sent(s["id"], s["email"], status, err)
            results["sent" if ok else "failed"] += 1
            results["details"].append({
                "name": s["name"], "email": s["email"],
                "class": s["class"], "status": status, "error": err
            })
            push_event({"type": "email_sent",
                        "name": s["name"], "status": status, "error": err})

    # Run synchronously for small batches, thread for large
    if len(students) <= 5:
        do_send()
        return jsonify({"success": True, **results})
    else:
        t = threading.Thread(target=do_send, daemon=True)
        t.start()
        return jsonify({"success": True, "async": True,
                        "total": len(students),
                        "message": f"Sending to {len(students)} students in background..."})

@app.route("/api/email-log")
@login_required
@admin_or_teacher
def api_email_log():
    return jsonify(get_email_log(50))

# ─── 404 handler ──────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

if __name__ == "__main__":
    app.run(debug=True, threaded=True, port=5000)
if __name__ == "__main__":
    app.run()