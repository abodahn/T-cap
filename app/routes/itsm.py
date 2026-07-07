from flask import Blueprint, render_template, request, redirect, url_for, abort, flash

from app.db import get_db, next_ref, utcnow, log_audit
from app.auth import login_required, permission_required, current_user, user_can
from app import itsm_core as core

bp = Blueprint("itsm", __name__, url_prefix="/itsm")


def _event(db, tid, kind, summary, detail="", internal=0, minutes=0, actor=None):
    u = current_user()
    db.execute(
        """INSERT INTO ticket_events(ticket_id,actor,kind,summary,detail,is_internal,
           minutes,created_at) VALUES(?,?,?,?,?,?,?,?)""",
        (tid, actor or (u["full_name"] if u else "system"), kind, summary, detail,
         internal, minutes, utcnow()))


def _stamp_first_response(db, t):
    if not t["first_response_at"]:
        db.execute("UPDATE tickets SET first_response_at=? WHERE id=?", (utcnow(), t["id"]))


@bp.route("/")
@permission_required("itsm_view")
def index():
    db = get_db()
    status = request.args.get("status") or ""
    priority = request.args.get("priority") or ""
    scope = request.args.get("scope") or ""
    q = (request.args.get("q") or "").strip()
    u = current_user()
    sql = "SELECT * FROM tickets WHERE 1=1"
    p = []
    if status:
        sql += " AND status=?"; p.append(status)
    if priority:
        sql += " AND priority=?"; p.append(priority)
    if scope == "mine":
        sql += " AND assigned_agent=?"; p.append(u["full_name"])
    elif scope == "unassigned":
        sql += " AND (assigned_agent IS NULL OR assigned_agent='')"
    if q:
        sql += " AND (subject LIKE ? OR ref LIKE ? OR requester LIKE ?)"; p += [f"%{q}%"] * 3
    sql += " ORDER BY (status IN ('Resolved','Closed','Cancelled')), sla_due"
    rows = db.execute(sql, p).fetchall()
    tickets = []
    for r in rows:
        sla = core.compute_sla(r)
        if scope == "breached" and not sla["breached"]:
            continue
        tickets.append({"r": r, "sla": sla})
    counts = {"": db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]}
    for s in core.STATUSES:
        c = db.execute("SELECT COUNT(*) FROM tickets WHERE status=?", (s,)).fetchone()[0]
        if c:
            counts[s] = c
    scope_counts = {
        "mine": db.execute("SELECT COUNT(*) FROM tickets WHERE assigned_agent=? AND status NOT IN ('Resolved','Closed','Cancelled')", (u["full_name"],)).fetchone()[0],
        "unassigned": db.execute("SELECT COUNT(*) FROM tickets WHERE (assigned_agent IS NULL OR assigned_agent='') AND status NOT IN ('Resolved','Closed','Cancelled')").fetchone()[0],
    }
    return render_template("itsm/list.html", tickets=tickets, statuses=core.STATUSES,
                           priorities=core.PRIORITIES, f_status=status, f_priority=priority,
                           scope=scope, q=q, counts=counts, scope_counts=scope_counts)


@bp.route("/export.xlsx")
@permission_required("itsm_view")
def export_xlsx():
    db = get_db()
    status = request.args.get("status") or ""
    priority = request.args.get("priority") or ""
    q = (request.args.get("q") or "").strip()
    sql = "SELECT * FROM tickets WHERE 1=1"; p = []
    if status:
        sql += " AND status=?"; p.append(status)
    if priority:
        sql += " AND priority=?"; p.append(priority)
    if q:
        sql += " AND (subject LIKE ? OR ref LIKE ?)"; p += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY created_at DESC"
    ts = db.execute(sql, p).fetchall()
    headers = ["Ref", "Subject", "Type", "Category", "Priority", "Status", "Requester",
               "Agent", "Site", "SLA Due", "Created"]
    rows = [(t["ref"], t["subject"], t["type"] or "", t["category"] or "", t["priority"],
             t["status"], t["requester"] or "", t["assigned_agent"] or "", t["site"] or "",
             (t["sla_due"] or "")[:16], (t["created_at"] or "")[:16]) for t in ts]
    from app.exports import xlsx_response
    return xlsx_response("tickets.xlsx", "Tickets", headers, rows)


@bp.route("/new", methods=["GET", "POST"])
@permission_required("itsm_create")
def new():
    db = get_db()
    if request.method == "POST":
        impact = request.form.get("impact") or "Single User"
        urgency = request.form.get("urgency") or "Medium"
        pri = core.derive_priority(impact, urgency)
        ref = next_ref(db, "tickets", "ref", "ITSM", year=True)
        u = current_user()
        resp_due = core.due_str(core.RESPONSE_MIN[pri])
        res_due = core.due_str(core.RESOLUTION_MIN[pri])
        db.execute(
            """INSERT INTO tickets(ref,subject,description,type,category,subcategory,
               priority,impact,urgency,status,requester,department,site,assigned_team,
               assigned_agent,asset_ref,sla_due,response_due,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ref, request.form.get("subject", "").strip(), request.form.get("description", "").strip(),
             request.form.get("type") or "Incident", request.form.get("category") or "Other",
             request.form.get("subcategory") or "", pri, impact, urgency, "New",
             request.form.get("requester") or u["full_name"],
             request.form.get("department") or u["department"],
             request.form.get("site") or u["site"], "Service Desk",
             request.form.get("assigned_agent") or "", request.form.get("asset_ref") or "",
             res_due, resp_due, utcnow(), utcnow()))
        tid = db.execute("SELECT id FROM tickets WHERE ref=?", (ref,)).fetchone()["id"]
        _event(db, tid, "system", "Ticket created", f"Priority {pri} ({impact} / {urgency})")
        db.commit()
        log_audit(u["username"], "itsm_create", ref)
        return redirect(url_for("itsm.view", ref=ref))
    agents = db.execute("SELECT full_name FROM users WHERE role IN ('it_agent','it_admin','monitoring_admin') ORDER BY full_name").fetchall()
    assets = db.execute("SELECT asset_id,name FROM assets ORDER BY asset_id").fetchall()
    return render_template("itsm/form.html", core=core, agents=agents, assets=assets, mode="new", tk=None)


@bp.route("/<ref>/edit", methods=["GET", "POST"])
@permission_required("itsm_edit")
def edit(ref):
    db = get_db()
    tk = db.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
    if not tk:
        abort(404)
    if request.method == "POST":
        from datetime import datetime, timezone
        impact = request.form.get("impact") or tk["impact"]
        urgency = request.form.get("urgency") or tk["urgency"]
        pri = core.derive_priority(impact, urgency)
        base = datetime.strptime(tk["created_at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        db.execute(
            """UPDATE tickets SET subject=?, description=?, type=?, category=?, subcategory=?,
               impact=?, urgency=?, priority=?, requester=?, department=?, site=?,
               asset_ref=?, sla_due=?, response_due=?, updated_at=? WHERE id=?""",
            (request.form.get("subject", "").strip(), request.form.get("description", "").strip(),
             request.form.get("type") or tk["type"], request.form.get("category") or tk["category"],
             request.form.get("subcategory") or "", impact, urgency, pri,
             request.form.get("requester") or tk["requester"],
             request.form.get("department") or tk["department"],
             request.form.get("site") or tk["site"], request.form.get("asset_ref") or "",
             core.due_str(core.RESOLUTION_MIN[pri], base), core.due_str(core.RESPONSE_MIN[pri], base),
             utcnow(), tk["id"]))
        _event(db, tk["id"], "system", "Ticket edited", f"Priority {pri} ({impact} × {urgency})")
        db.commit()
        log_audit(current_user()["username"], "itsm_edit_fields", ref)
        return redirect(url_for("itsm.view", ref=ref))
    agents = db.execute("SELECT full_name FROM users WHERE role IN ('it_agent','it_admin','monitoring_admin') ORDER BY full_name").fetchall()
    assets = db.execute("SELECT asset_id,name FROM assets ORDER BY asset_id").fetchall()
    return render_template("itsm/form.html", core=core, agents=agents, assets=assets, mode="edit", tk=tk)


@bp.route("/<ref>")
@permission_required("itsm_view")
def view(ref):
    db = get_db()
    t = db.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
    if not t:
        abort(404)
    sla = core.compute_sla(t)
    internal_ok = user_can("itsm_edit")
    if internal_ok:
        events = db.execute("SELECT * FROM ticket_events WHERE ticket_id=? ORDER BY created_at, id", (t["id"],)).fetchall()
    else:
        events = db.execute("SELECT * FROM ticket_events WHERE ticket_id=? AND is_internal=0 ORDER BY created_at, id", (t["id"],)).fetchall()
    asset = db.execute("SELECT asset_id,name FROM assets WHERE asset_id=?", (t["asset_ref"],)).fetchone() if t["asset_ref"] else None
    agents = db.execute("SELECT full_name FROM users WHERE role IN ('it_agent','it_admin','monitoring_admin') ORDER BY full_name").fetchall()
    return render_template("itsm/detail.html", ticket=t, sla=sla, events=events, asset=asset,
                           agents=agents, core=core, can_edit=internal_ok)


@bp.route("/<ref>/action", methods=["POST"])
@permission_required("itsm_edit")
def action(ref):
    db = get_db()
    t = db.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
    if not t:
        abort(404)
    u = current_user()
    a = request.form.get("action")
    now = utcnow()

    if a == "assign_me":
        db.execute("UPDATE tickets SET assigned_agent=?, status=CASE WHEN status='New' THEN 'Assigned' ELSE status END, updated_at=? WHERE id=?",
                   (u["full_name"], now, t["id"]))
        _stamp_first_response(db, t)
        _event(db, t["id"], "assign", f"Assigned to {u['full_name']}")

    elif a == "assign":
        who = request.form.get("assigned_agent") or ""
        db.execute("UPDATE tickets SET assigned_agent=?, status=CASE WHEN status='New' THEN 'Assigned' ELSE status END, updated_at=? WHERE id=?",
                   (who, now, t["id"]))
        _event(db, t["id"], "assign", f"Assigned to {who or 'unassigned'}")
        if who and who != u["full_name"]:
            from app.notify import notify_assignment
            notify_assignment(db, t, who)

    elif a == "status":
        new_status = request.form.get("status")
        if new_status in core.STATUSES and new_status != t["status"]:
            db.execute("UPDATE tickets SET status=?, updated_at=? WHERE id=?", (new_status, now, t["id"]))
            _stamp_first_response(db, t)
            _event(db, t["id"], "status", f"Status → {new_status}")

    elif a == "comment":
        body = (request.form.get("comment") or "").strip()
        internal = 1 if request.form.get("internal") else 0
        if body:
            _stamp_first_response(db, t)
            _event(db, t["id"], "note" if internal else "comment", body,
                   internal=internal)

    elif a == "worklog":
        try:
            mins = max(0, int(request.form.get("minutes") or 0))
        except ValueError:
            mins = 0
        summary = (request.form.get("summary") or "Work logged").strip()
        if mins:
            db.execute("UPDATE tickets SET time_spent_min=COALESCE(time_spent_min,0)+? WHERE id=?", (mins, t["id"]))
            _event(db, t["id"], "worklog", summary, detail=f"{mins} min", minutes=mins)

    elif a == "resolve":
        resolution = (request.form.get("resolution") or "").strip()
        closure = request.form.get("closure_category") or "Resolved Permanently"
        if not resolution:
            flash("resolution_required")
            return redirect(url_for("itsm.view", ref=ref))
        db.execute("""UPDATE tickets SET status='Resolved', resolved_at=?, resolution=?,
                      closure_category=?, root_cause=?, updated_at=? WHERE id=?""",
                   (now, resolution, closure, request.form.get("root_cause") or "", now, t["id"]))
        _stamp_first_response(db, t)
        _event(db, t["id"], "resolve", f"Resolved · {closure}", detail=resolution)

    elif a == "close":
        db.execute("UPDATE tickets SET status='Closed', closed_at=?, updated_at=? WHERE id=?", (now, now, t["id"]))
        _event(db, t["id"], "status", "Ticket closed")

    elif a == "reopen":
        if t["status"] == "Resolved":
            reason = (request.form.get("reason") or "").strip()
            res_due = core.due_str(core.RESOLUTION_MIN.get(t["priority"], 1440))
            db.execute("""UPDATE tickets SET status='Reopened', resolved_at=NULL, closed_at=NULL,
                          reopen_reason=?, sla_due=?, updated_at=? WHERE id=?""",
                       (reason, res_due, now, t["id"]))
            _event(db, t["id"], "reopen", "Ticket reopened", detail=reason)

    elif a == "escalate":
        reason = (request.form.get("reason") or "").strip()
        db.execute("UPDATE tickets SET escalation_level=COALESCE(escalation_level,0)+1, updated_at=? WHERE id=?", (now, t["id"]))
        _event(db, t["id"], "escalate", "Escalated", detail=reason, internal=1)

    db.commit()
    log_audit(u["username"], f"itsm_{a}", ref)
    return redirect(url_for("itsm.view", ref=ref) + "#activity")
