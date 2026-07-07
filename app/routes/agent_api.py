"""Agent ingestion API. A device's agent POSTs metrics here with its enrollment
token. Token-authenticated (not session), and CSRF-exempt (see app.csrf)."""
from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash

from app.db import get_db, utcnow

bp = Blueprint("agent_api", __name__)


def _open_alert(db, host, kind):
    return db.execute(
        "SELECT id FROM mon_alerts WHERE endpoint=? AND kind=? AND status='open'",
        (host, kind)).fetchone()


def _upsert_alert(db, host, severity, kind, message):
    row = _open_alert(db, host, kind)
    if row:
        db.execute("UPDATE mon_alerts SET severity=?, message=? WHERE id=?", (severity, message, row["id"]))
    else:
        db.execute(
            "INSERT INTO mon_alerts(endpoint,severity,kind,message,status,created_at) VALUES(?,?,?,?, 'open',?)",
            (host, severity, kind, message, utcnow()))


def _resolve_alert(db, host, kind):
    db.execute("UPDATE mon_alerts SET status='resolved' WHERE endpoint=? AND kind=? AND status='open'", (host, kind))


@bp.post("/api/agent/metrics")
def metrics():
    data = request.get_json(silent=True) or request.form
    hostname = (data.get("hostname") or "").strip()
    token = data.get("token") or request.headers.get("X-Agent-Token", "")
    if not hostname or not token:
        return jsonify(ok=False, error="missing hostname or token"), 400
    db = get_db()
    e = db.execute("SELECT * FROM endpoints WHERE hostname=?", (hostname,)).fetchone()
    if not e or not e["api_token_hash"] or not check_password_hash(e["api_token_hash"], token):
        return jsonify(ok=False, error="unauthorized"), 401

    def num(k, d):
        try:
            return float(data.get(k, d))
        except (TypeError, ValueError):
            return d

    cpu, ram, disk = num("cpu", e["cpu"]), num("ram", e["ram"]), num("disk", e["disk"])
    uptime = num("uptime_h", e["uptime_h"])
    ver = data.get("agent_ver") or e["agent_ver"]

    rules = {r["metric"]: r for r in db.execute("SELECT * FROM mon_rules WHERE enabled=1").fetchall()}
    status = "online"
    for metric, val in (("cpu", cpu), ("ram", ram), ("disk", disk)):
        r = rules.get(metric)
        if not r:
            continue
        if val >= r["crit"]:
            _upsert_alert(db, hostname, "critical", metric, f"{r['label']} at {val:.0f}% (>= {r['crit']:.0f}%)")
            status = "warning"
        elif val >= r["warn"]:
            _upsert_alert(db, hostname, "warning", metric, f"{r['label']} at {val:.0f}% (>= {r['warn']:.0f}%)")
            status = "warning"
        else:
            _resolve_alert(db, hostname, metric)

    db.execute(
        "UPDATE endpoints SET cpu=?,ram=?,disk=?,uptime_h=?,agent_ver=?,status=?,last_seen=? WHERE id=?",
        (cpu, ram, disk, uptime, ver, status, utcnow(), e["id"]))
    db.commit()
    return jsonify(ok=True, hostname=hostname, status=status)
