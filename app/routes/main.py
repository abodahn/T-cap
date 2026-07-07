from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash

from app.db import get_db, log_audit
from app.auth import login_required, permission_required, current_user

bp = Blueprint("main", __name__)


@bp.route("/healthz")
def healthz():
    return jsonify(status="ok", app="t-cap")


@bp.route("/")
def index():
    if current_user():
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


def _kpis(db):
    def one(sql, *p):
        r = db.execute(sql, p).fetchone()
        return r[0] if r else 0
    open_tickets = one("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('Resolved','Closed')")
    total_tickets = one("SELECT COUNT(*) FROM tickets")
    resolved = one("SELECT COUNT(*) FROM tickets WHERE status IN ('Resolved','Closed')")
    breached = one("SELECT COUNT(*) FROM tickets WHERE sla_due < datetime('now') AND status NOT IN ('Resolved','Closed')")
    total_assets = one("SELECT COUNT(*) FROM assets")
    book_value = one("SELECT COALESCE(SUM(purchase_value),0) FROM assets")
    low_stock = one("SELECT COUNT(*) FROM stock_items WHERE quantity <= min_stock")
    endpoints = one("SELECT COUNT(*) FROM endpoints")
    offline = one("SELECT COUNT(*) FROM endpoints WHERE status='offline'")
    open_alerts = one("SELECT COUNT(*) FROM mon_alerts WHERE status='open'")
    sla = round((resolved / total_tickets * 100) if total_tickets else 100, 1)
    health = max(0, 100 - breached * 4 - offline * 5 - low_stock * 2 - open_alerts * 3)
    return dict(open_tickets=open_tickets, sla=sla, breached=breached,
                total_assets=total_assets, book_value=book_value, low_stock=low_stock,
                endpoints=endpoints, offline=offline, open_alerts=open_alerts,
                health=min(health, 100), resolved=resolved)


@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    from app.notify import run_checks
    run_checks(db)
    kpis = _kpis(db)
    recent_tickets = db.execute(
        "SELECT * FROM tickets ORDER BY created_at DESC LIMIT 7").fetchall()
    alerts = db.execute(
        "SELECT * FROM mon_alerts WHERE status='open' ORDER BY created_at DESC LIMIT 5").fetchall()
    prio = {p: db.execute("SELECT COUNT(*) FROM tickets WHERE priority=? AND status NOT IN ('Resolved','Closed')", (p,)).fetchone()[0]
            for p in ("Critical", "High", "Medium", "Low")}
    status_dist = db.execute(
        "SELECT status, COUNT(*) c FROM tickets GROUP BY status ORDER BY c DESC").fetchall()
    cat_dist = db.execute(
        "SELECT category, COUNT(*) c FROM assets GROUP BY category ORDER BY c DESC").fetchall()
    ep_dist = db.execute(
        "SELECT status, COUNT(*) c FROM endpoints GROUP BY status").fetchall()
    # tickets created per day, last 7 days (oldest -> newest) for the sparkline
    from datetime import date, timedelta
    per_day = []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        per_day.append(db.execute(
            "SELECT COUNT(*) FROM tickets WHERE substr(created_at,1,10)=?", (d,)).fetchone()[0])
    return render_template("dashboard.html", kpis=kpis, recent_tickets=recent_tickets,
                           alerts=alerts, prio=prio, status_dist=status_dist,
                           cat_dist=cat_dist, ep_dist=ep_dist, per_day=per_day)


@bp.route("/reports")
@permission_required("reports_view")
def reports():
    db = get_db()
    f = _report_filters()
    kpis = _kpis(db)                        # global baseline (endpoints/stock/alerts)
    fk, by_status, by_cat = _report_data(db, f)
    kpis.update(fk)                         # scope ticket/asset aggregates by the filter
    return render_template("reports.html", kpis=kpis, by_status=by_status, by_cat=by_cat, f=f)


def _report_filters():
    return {k: (request.args.get(k) or "").strip() for k in ("date_from", "date_to", "site", "department")}


def _report_data(db, f):
    tc, tp, ac, ap = [], [], [], []
    if f.get("date_from"):
        tc.append("substr(created_at,1,10)>=?"); tp.append(f["date_from"])
        ac.append("substr(created_at,1,10)>=?"); ap.append(f["date_from"])
    if f.get("date_to"):
        tc.append("substr(created_at,1,10)<=?"); tp.append(f["date_to"])
        ac.append("substr(created_at,1,10)<=?"); ap.append(f["date_to"])
    if f.get("site"):
        tc.append("site=?"); tp.append(f["site"]); ac.append("site=?"); ap.append(f["site"])
    if f.get("department"):
        tc.append("department=?"); tp.append(f["department"]); ac.append("department=?"); ap.append(f["department"])
    tw = (" WHERE " + " AND ".join(tc)) if tc else ""
    aw = (" WHERE " + " AND ".join(ac)) if ac else ""
    tj = " AND " if tw else " WHERE "

    def one(sql, p=()):
        r = db.execute(sql, p).fetchone()
        return r[0] if r else 0
    total_t = one("SELECT COUNT(*) FROM tickets" + tw, tp)
    resolved = one("SELECT COUNT(*) FROM tickets" + tw + tj + "status IN ('Resolved','Closed')", tp)
    kpis = {
        "open_tickets": one("SELECT COUNT(*) FROM tickets" + tw + tj + "status NOT IN ('Resolved','Closed')", tp),
        "breached": one("SELECT COUNT(*) FROM tickets" + tw + tj + "sla_due < datetime('now') AND status NOT IN ('Resolved','Closed')", tp),
        "total_assets": one("SELECT COUNT(*) FROM assets" + aw, ap),
        "book_value": one("SELECT COALESCE(SUM(purchase_value),0) FROM assets" + aw, ap),
        "sla": round((resolved / total_t * 100) if total_t else 100, 1),
    }
    by_status = db.execute("SELECT status, COUNT(*) c FROM tickets" + tw + " GROUP BY status ORDER BY c DESC", tp).fetchall()
    by_cat = db.execute("SELECT category, COUNT(*) c FROM assets" + aw + " GROUP BY category ORDER BY c DESC", ap).fetchall()
    return kpis, by_status, by_cat


def _filter_summary(f):
    parts = []
    if f.get("date_from") or f.get("date_to"):
        parts.append(f"{f.get('date_from') or '…'} → {f.get('date_to') or '…'}")
    if f.get("site"):
        parts.append(f["site"])
    if f.get("department"):
        parts.append(f["department"])
    return " · ".join(parts) if parts else "All data"


@bp.route("/reports/export.pdf")
@permission_required("reports_view")
def reports_pdf():
    db = get_db()
    f = _report_filters()
    k = _kpis(db)
    fk, by_status, by_cat = _report_data(db, f)
    k.update(fk)
    from app.exports import pdf_report_response
    sections = [
        ("Key Indicators", ["Metric", "Value"], [
            ("Open Tickets", k["open_tickets"]), ("SLA Compliance", f"{k['sla']}%"),
            ("Breached", k["breached"]), ("Total Assets", k["total_assets"]),
            ("Book Value", f"${k['book_value']:,.0f}"), ("Low Stock", k["low_stock"]),
            ("Endpoints", k["endpoints"]), ("Offline", k["offline"]), ("Open Alerts", k["open_alerts"])]),
        ("Tickets by Status", ["Status", "Count"], [(r["status"], r["c"]) for r in by_status]),
        ("Assets by Category", ["Category", "Count"], [(r["category"], r["c"]) for r in by_cat]),
    ]
    meta = {"generated_by": current_user()["full_name"], "filters": _filter_summary(f)}
    return pdf_report_response("tcap-executive-report.pdf", "Executive Report", meta, sections)


@bp.route("/search")
@login_required
def search():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    results = {"tickets": [], "assets": [], "endpoints": []}
    if q:
        like = f"%{q}%"
        results["tickets"] = db.execute(
            "SELECT ref,subject,status FROM tickets WHERE subject LIKE ? OR ref LIKE ? LIMIT 10", (like, like)).fetchall()
        results["assets"] = db.execute(
            "SELECT asset_id,name,status FROM assets WHERE name LIKE ? OR asset_id LIKE ? OR serial LIKE ? LIMIT 10", (like, like, like)).fetchall()
        results["endpoints"] = db.execute(
            "SELECT hostname,ip,status FROM endpoints WHERE hostname LIKE ? OR ip LIKE ? LIMIT 10", (like, like)).fetchall()
    return render_template("search.html", q=q, results=results)


@bp.route("/notifications")
@login_required
def notifications():
    db = get_db()
    from app.notify import run_checks
    run_checks(db)
    me = current_user()["username"]
    items = db.execute(
        """SELECT * FROM notifications WHERE target_user IS NULL OR target_user=?
           ORDER BY is_read, created_at DESC LIMIT 60""", (me,)).fetchall()
    return render_template("notifications.html", items=items)


@bp.route("/notifications/read", methods=["POST"])
@login_required
def notifications_read():
    db = get_db()
    me = current_user()["username"]
    db.execute("UPDATE notifications SET is_read=1 WHERE target_user IS NULL OR target_user=?", (me,))
    db.commit()
    return redirect(url_for("main.notifications"))


@bp.route("/workspace")
@permission_required("itsm_edit")
def workspace():
    db = get_db()
    from app import itsm_core as core
    me = current_user()["full_name"]
    OPEN = "('New','Assigned','In Progress','Waiting User','Waiting Vendor','On Hold','Reopened')"

    def rows(where, params=()):
        return db.execute(f"SELECT * FROM tickets WHERE {where} ORDER BY sla_due", params).fetchall()

    my_open = rows(f"assigned_agent=? AND status IN {OPEN}", (me,))
    unassigned = rows(f"(assigned_agent IS NULL OR assigned_agent='') AND status IN {OPEN}")
    critical = rows(f"priority='Critical' AND status IN {OPEN}")
    all_open = rows(f"status IN {OPEN}")
    breached = [r for r in all_open if core.compute_sla(r)["breached"]]
    resolved_today = rows("status IN ('Resolved','Closed') AND substr(resolved_at,1,10)=date('now')")

    def pack(rs, limit=8):
        return {"count": len(rs), "items": [{"r": r, "sla": core.compute_sla(r)} for r in rs[:limit]]}

    queues = [
        ("my_open", pack(my_open)),
        ("unassigned", pack(unassigned)),
        ("breached", pack(breached)),
        ("critical", pack(critical)),
        ("resolved_today", pack(resolved_today)),
    ]
    return render_template("workspace.html", queues=queues, me=me)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    u = current_user()
    if request.method == "POST":
        from werkzeug.security import check_password_hash, generate_password_hash
        cur = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        if not check_password_hash(u["password_hash"], cur):
            flash("wrong_password")
        elif len(new) < 8:
            flash("password_too_short")
        else:
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (generate_password_hash(new), u["id"]))
            db.commit()
            log_audit(u["username"], "password_change")
            flash("password_changed")
        return redirect(url_for("main.profile"))
    stats = dict(
        tickets=db.execute("SELECT COUNT(*) FROM tickets WHERE assigned_agent=?", (u["full_name"],)).fetchone()[0],
        actions=db.execute("SELECT COUNT(*) FROM audit_logs WHERE username=?", (u["username"],)).fetchone()[0],
    )
    return render_template("profile.html", u=u, stats=stats)


@bp.route("/api/notifications/count")
@login_required
def notif_count():
    db = get_db()
    me = current_user()["username"]
    n = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE is_read=0 AND (target_user IS NULL OR target_user=?)",
        (me,)).fetchone()[0]
    return jsonify(unread=n)


@bp.route("/api/notifications/list")
@login_required
def notif_list():
    db = get_db()
    from app.notify import run_checks
    run_checks(db)
    me = current_user()["username"]
    rows = db.execute(
        """SELECT id,severity,title,message,link,is_read,created_at FROM notifications
           WHERE target_user IS NULL OR target_user=? ORDER BY is_read, created_at DESC LIMIT 12""",
        (me,)).fetchall()
    unread = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE is_read=0 AND (target_user IS NULL OR target_user=?)",
        (me,)).fetchone()[0]
    items = [{k: r[k] for k in r.keys()} for r in rows]
    return jsonify(unread=unread, items=items)
