import secrets

from flask import (Blueprint, render_template, request, redirect, url_for, abort, flash)
from werkzeug.security import generate_password_hash

from app.db import get_db, next_ref, utcnow, log_audit
from app.auth import permission_required, current_user, user_can

bp = Blueprint("monitoring", __name__, url_prefix="/monitoring")

SITES = ["Head Office", "Textile Factory", "Central Warehouse", "Real Estate Office"]


@bp.route("/")
@permission_required("mon_view")
def index():
    db = get_db()
    endpoints = db.execute("SELECT * FROM endpoints ORDER BY status DESC, hostname").fetchall()
    alerts = db.execute("SELECT * FROM mon_alerts ORDER BY created_at DESC").fetchall()
    online = sum(1 for e in endpoints if e["status"] == "online")
    warning = sum(1 for e in endpoints if e["status"] == "warning")
    offline = sum(1 for e in endpoints if e["status"] == "offline")
    open_alerts = sum(1 for a in alerts if a["status"] == "open")
    crit = sum(1 for a in alerts if a["status"] == "open" and a["severity"] == "critical")
    total = len(endpoints) or 1
    health = round(max(0, (online + warning * 0.5) / total * 100 - crit * 5))
    stats = dict(total=len(endpoints), online=online, warning=warning, offline=offline,
                 open_alerts=open_alerts, crit=crit, health=health)
    sev = {s: sum(1 for a in alerts if a["severity"] == s) for s in ("critical", "warning", "info")}
    return render_template("monitoring/list.html", endpoints=endpoints, alerts=alerts,
                           stats=stats, sev=sev)


@bp.route("/endpoint/<hostname>")
@permission_required("mon_view")
def view(hostname):
    db = get_db()
    e = db.execute("SELECT * FROM endpoints WHERE hostname=?", (hostname,)).fetchone()
    if not e:
        abort(404)
    alerts = db.execute("SELECT * FROM mon_alerts WHERE endpoint=? ORDER BY created_at DESC", (hostname,)).fetchall()
    asset = db.execute("SELECT asset_id,name FROM assets WHERE asset_id=?", (e["asset_ref"],)).fetchone() if e["asset_ref"] else None
    return render_template("monitoring/detail.html", e=e, alerts=alerts, asset=asset,
                           can_manage=user_can("mon_manage"))


@bp.route("/enroll", methods=["GET", "POST"])
@permission_required("mon_manage")
def enroll():
    db = get_db()
    error = None
    if request.method == "POST":
        hostname = (request.form.get("hostname") or "").strip()
        if not hostname:
            error = "required_fields"
        elif db.execute("SELECT 1 FROM endpoints WHERE hostname=?", (hostname,)).fetchone():
            error = "hostname_taken"
        if not error:
            token = secrets.token_urlsafe(24)
            db.execute(
                """INSERT INTO endpoints(hostname,ip,os,site,department,status,cpu,ram,disk,
                   uptime_h,agent_ver,last_seen,asset_ref,api_token_hash,enrolled_at,maintenance)
                   VALUES(?,?,?,?,?,'offline',0,0,0,0,'—','',?,?,?,0)""",
                (hostname, request.form.get("ip") or "", request.form.get("os") or "Windows",
                 request.form.get("site") or "Head Office", request.form.get("department") or "IT",
                 request.form.get("asset_ref") or "", generate_password_hash(token), utcnow()))
            db.commit()
            log_audit(current_user()["username"], "endpoint_enroll", hostname)
            flash(f"enrolled:{hostname}:{token}")
            return redirect(url_for("monitoring.view", hostname=hostname))
    assets = db.execute("SELECT asset_id,name FROM assets ORDER BY asset_id").fetchall()
    return render_template("monitoring/enroll.html", sites=SITES, assets=assets, error=error)


@bp.route("/rules", methods=["GET", "POST"])
@permission_required("mon_manage")
def rules():
    db = get_db()
    if request.method == "POST":
        for r in db.execute("SELECT * FROM mon_rules").fetchall():
            try:
                warn = float(request.form.get(f"warn_{r['id']}") or r["warn"])
                crit = float(request.form.get(f"crit_{r['id']}") or r["crit"])
            except ValueError:
                warn, crit = r["warn"], r["crit"]
            enabled = 1 if request.form.get(f"enabled_{r['id']}") else 0
            db.execute("UPDATE mon_rules SET warn=?, crit=?, enabled=? WHERE id=?", (warn, crit, enabled, r["id"]))
        db.commit()
        log_audit(current_user()["username"], "mon_rules_save", "thresholds updated")
        return redirect(url_for("monitoring.rules"))
    rules = db.execute("SELECT * FROM mon_rules ORDER BY id").fetchall()
    return render_template("monitoring/rules.html", rules=rules)


@bp.route("/endpoint/<hostname>/maintenance", methods=["POST"])
@permission_required("mon_manage")
def toggle_maint(hostname):
    db = get_db()
    e = db.execute("SELECT * FROM endpoints WHERE hostname=?", (hostname,)).fetchone()
    if not e:
        abort(404)
    db.execute("UPDATE endpoints SET maintenance=? WHERE id=?", (0 if e["maintenance"] else 1, e["id"]))
    db.commit()
    log_audit(current_user()["username"], "endpoint_maintenance", hostname)
    return redirect(url_for("monitoring.view", hostname=hostname))


@bp.route("/endpoint/<hostname>/edit", methods=["GET", "POST"])
@permission_required("mon_manage")
def edit(hostname):
    db = get_db()
    e = db.execute("SELECT * FROM endpoints WHERE hostname=?", (hostname,)).fetchone()
    if not e:
        abort(404)
    if request.method == "POST":
        db.execute(
            "UPDATE endpoints SET ip=?, os=?, site=?, department=?, asset_ref=? WHERE id=?",
            (request.form.get("ip") or e["ip"], request.form.get("os") or e["os"],
             request.form.get("site") or e["site"], request.form.get("department") or e["department"],
             request.form.get("asset_ref") or "", e["id"]))
        db.commit()
        log_audit(current_user()["username"], "endpoint_edit", hostname)
        return redirect(url_for("monitoring.view", hostname=hostname))
    assets = db.execute("SELECT asset_id,name FROM assets ORDER BY asset_id").fetchall()
    return render_template("monitoring/endpoint_form.html", e=e, sites=SITES, assets=assets)


@bp.route("/endpoint/<hostname>/delete", methods=["POST"])
@permission_required("mon_manage")
def delete(hostname):
    db = get_db()
    e = db.execute("SELECT id FROM endpoints WHERE hostname=?", (hostname,)).fetchone()
    if not e:
        abort(404)
    db.execute("DELETE FROM mon_alerts WHERE endpoint=?", (hostname,))
    db.execute("DELETE FROM endpoints WHERE id=?", (e["id"],))
    db.commit()
    log_audit(current_user()["username"], "endpoint_delete", hostname)
    return redirect(url_for("monitoring.index"))


@bp.route("/alert/<int:alert_id>/<string:act>", methods=["POST"])
@permission_required("mon_manage")
def alert_action(alert_id, act):
    db = get_db()
    a = db.execute("SELECT * FROM mon_alerts WHERE id=?", (alert_id,)).fetchone()
    if not a:
        abort(404)
    if act in ("acknowledged", "resolved"):
        db.execute("UPDATE mon_alerts SET status=? WHERE id=?", (act, alert_id))
        db.commit()
        log_audit(current_user()["username"], f"alert_{act}", a["endpoint"])
    return redirect(request.referrer or url_for("monitoring.index"))


@bp.route("/alert/<int:alert_id>/to-ticket", methods=["POST"])
@permission_required("mon_manage")
def alert_to_ticket(alert_id):
    db = get_db()
    a = db.execute("SELECT * FROM mon_alerts WHERE id=?", (alert_id,)).fetchone()
    if not a:
        abort(404)
    if a["ticket_ref"]:
        return redirect(url_for("itsm.view", ref=a["ticket_ref"]))
    from datetime import datetime, timedelta, timezone
    ref = next_ref(db, "tickets", "ref", "ITSM", year=True)
    now = datetime.now(timezone.utc)
    pri = "Critical" if a["severity"] == "critical" else "High"
    ep = db.execute("SELECT * FROM endpoints WHERE hostname=?", (a["endpoint"],)).fetchone()
    u = current_user()
    db.execute(
        """INSERT INTO tickets(ref,subject,description,type,category,priority,impact,urgency,
           status,requester,department,site,assigned_team,assigned_agent,asset_ref,
           sla_due,response_due,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ref, f"[Monitoring] {a['message']}", f"Auto-created from alert on {a['endpoint']}.",
         "Incident", "Infrastructure", pri, "Department", pri, "New", "monitoring-automation",
         ep["department"] if ep else "IT", ep["site"] if ep else "Head Office",
         "Service Desk", "", ep["asset_ref"] if ep else "",
         (now + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
         (now + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"), utcnow(), utcnow()))
    tid = db.execute("SELECT id FROM tickets WHERE ref=?", (ref,)).fetchone()["id"]
    db.execute("INSERT INTO ticket_events(ticket_id,actor,kind,summary,created_at) VALUES(?,?,?,?,?)",
               (tid, "monitoring", "system", f"Auto-created from alert on {a['endpoint']}", utcnow()))
    db.execute("UPDATE mon_alerts SET ticket_ref=?, status='acknowledged' WHERE id=?", (ref, alert_id))
    db.commit()
    log_audit(u["username"], "alert_to_ticket", f"{a['endpoint']} -> {ref}")
    return redirect(url_for("itsm.view", ref=ref))
