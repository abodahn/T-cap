from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, abort

from app.db import get_db, next_ref, utcnow, log_audit
from app.auth import permission_required, current_user, user_can

bp = Blueprint("asm", __name__, url_prefix="/asm")

STATUSES = ["In Stock", "Assigned", "Under Maintenance", "Lost", "Scrapped", "Disposed"]
CATEGORIES = ["Server", "Laptop", "Desktop", "Printer", "Network", "Power", "Mobile", "Other"]
SITES = ["Head Office", "Textile Factory", "Central Warehouse", "Real Estate Office"]


def _event(db, aid, kind, summary, detail="", cost=0):
    u = current_user()
    db.execute(
        """INSERT INTO asset_events(asset_id,actor,kind,summary,detail,cost,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (aid, u["full_name"] if u else "system", kind, summary, detail, cost, utcnow()))


def _warranty(a):
    if not a["warranty_end"]:
        return "none"
    try:
        d = (date.fromisoformat(a["warranty_end"]) - date.today()).days
        return "expired" if d < 0 else ("expiring" if d <= 60 else "valid")
    except Exception:
        return "none"


def _book(a):
    if not (a["purchase_date"] and (a["purchase_value"] or 0) > 0):
        return a["purchase_value"] or 0
    try:
        age = (date.today() - date.fromisoformat(a["purchase_date"])).days / 365.25
        return round(a["purchase_value"] * max(0.0, 1 - age / 5.0), 2)
    except Exception:
        return a["purchase_value"] or 0


@bp.route("/")
@permission_required("asm_view")
def index():
    db = get_db()
    status = request.args.get("status") or ""
    cat = request.args.get("category") or ""
    q = (request.args.get("q") or "").strip()
    sql = "SELECT * FROM assets WHERE 1=1"; p = []
    if status:
        sql += " AND status=?"; p.append(status)
    if cat:
        sql += " AND category=?"; p.append(cat)
    if q:
        sql += " AND (name LIKE ? OR asset_id LIKE ? OR serial LIKE ? OR custodian LIKE ?)"; p += [f"%{q}%"] * 4
    sql += " ORDER BY asset_id"
    assets = db.execute(sql, p).fetchall()
    counts = {"": db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]}
    for s in STATUSES:
        c = db.execute("SELECT COUNT(*) FROM assets WHERE status=?", (s,)).fetchone()[0]
        if c:
            counts[s] = c
    return render_template("asm/list.html", assets=assets, statuses=STATUSES,
                           categories=CATEGORIES, f_status=status, f_cat=cat, q=q, counts=counts)


def _agents(db):
    return db.execute("SELECT full_name FROM users WHERE is_active=1 ORDER BY full_name").fetchall()


@bp.route("/export.xlsx")
@permission_required("asm_view")
def export_xlsx():
    db = get_db()
    status = request.args.get("status") or ""
    cat = request.args.get("category") or ""
    q = (request.args.get("q") or "").strip()
    sql = "SELECT * FROM assets WHERE 1=1"; p = []
    if status:
        sql += " AND status=?"; p.append(status)
    if cat:
        sql += " AND category=?"; p.append(cat)
    if q:
        sql += " AND (name LIKE ? OR asset_id LIKE ? OR serial LIKE ?)"; p += [f"%{q}%"] * 3
    sql += " ORDER BY asset_id"
    a = db.execute(sql, p).fetchall()
    headers = ["Asset ID", "Name", "Category", "Brand", "Model", "Serial", "Company",
               "Site", "Department", "Custodian", "Status", "Purchase Value", "Warranty End"]
    rows = [(x["asset_id"], x["name"], x["category"] or "", x["brand"] or "", x["model"] or "",
             x["serial"] or "", x["company"] or "", x["site"] or "", x["department"] or "",
             x["custodian"] or "", x["status"], x["purchase_value"] or 0, x["warranty_end"] or "")
            for x in a]
    from app.exports import xlsx_response
    return xlsx_response("assets.xlsx", "Assets", headers, rows)


@bp.route("/new", methods=["GET", "POST"])
@permission_required("asm_create")
def new():
    db = get_db()
    if request.method == "POST":
        aid = next_ref(db, "assets", "asset_id", "AST")
        db.execute(
            """INSERT INTO assets(asset_id,name,category,brand,model,serial,company,
               site,department,custodian,status,purchase_date,purchase_value,
               warranty_end,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, request.form.get("name", "").strip(), request.form.get("category") or "Other",
             request.form.get("brand", ""), request.form.get("model", ""),
             request.form.get("serial", ""), request.form.get("company", ""),
             request.form.get("site", ""), request.form.get("department", ""),
             request.form.get("custodian", ""), request.form.get("status") or "In Stock",
             request.form.get("purchase_date") or None,
             float(request.form.get("purchase_value") or 0),
             request.form.get("warranty_end") or None, utcnow()))
        row = db.execute("SELECT id FROM assets WHERE asset_id=?", (aid,)).fetchone()
        _event(db, row["id"], "system", "Asset registered")
        db.commit()
        log_audit(current_user()["username"], "asm_create", aid)
        return redirect(url_for("asm.view", asset_id=aid))
    return render_template("asm/form.html", statuses=STATUSES, categories=CATEGORIES,
                           sites=SITES, agents=_agents(db), mode="new", a=None)


@bp.route("/asset/<asset_id>")
@permission_required("asm_view")
def view(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    if not a:
        abort(404)
    tickets = db.execute(
        "SELECT ref,subject,status FROM tickets WHERE asset_ref=? ORDER BY created_at DESC", (asset_id,)).fetchall()
    endpoint = db.execute("SELECT * FROM endpoints WHERE asset_ref=?", (asset_id,)).fetchone()
    events = db.execute("SELECT * FROM asset_events WHERE asset_id=? ORDER BY created_at DESC, id DESC", (a["id"],)).fetchall()
    maint_total = db.execute("SELECT COALESCE(SUM(cost),0) FROM asset_events WHERE asset_id=? AND kind='maintenance'", (a["id"],)).fetchone()[0]
    return render_template("asm/detail.html", a=a, tickets=tickets, endpoint=endpoint,
                           statuses=STATUSES, warr=_warranty(a), book=_book(a),
                           events=events, agents=_agents(db), sites=SITES,
                           maint_total=maint_total, can_edit=user_can("asm_edit"),
                           can_delete=user_can("asm_delete"))


@bp.route("/asset/<asset_id>/edit", methods=["GET", "POST"])
@permission_required("asm_edit")
def edit(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    if not a:
        abort(404)
    if request.method == "POST":
        db.execute(
            """UPDATE assets SET name=?, category=?, brand=?, model=?, serial=?, company=?,
               department=?, purchase_date=?, purchase_value=?, warranty_end=? WHERE id=?""",
            (request.form.get("name", "").strip(), request.form.get("category") or a["category"],
             request.form.get("brand", ""), request.form.get("model", ""),
             request.form.get("serial", ""), request.form.get("company", ""),
             request.form.get("department", ""), request.form.get("purchase_date") or None,
             float(request.form.get("purchase_value") or 0),
             request.form.get("warranty_end") or None, a["id"]))
        _event(db, a["id"], "edit", "Asset details edited")
        db.commit()
        log_audit(current_user()["username"], "asm_edit", asset_id)
        return redirect(url_for("asm.view", asset_id=asset_id))
    return render_template("asm/form.html", statuses=STATUSES, categories=CATEGORIES,
                           sites=SITES, agents=_agents(db), mode="edit", a=a)


@bp.route("/asset/<asset_id>/action", methods=["POST"])
@permission_required("asm_edit")
def action(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    if not a:
        abort(404)
    act = request.form.get("action")

    if act == "custody_assign":
        who = (request.form.get("custodian") or "").strip()
        if who:
            db.execute("UPDATE assets SET custodian=?, status=CASE WHEN status='In Stock' THEN 'Assigned' ELSE status END WHERE id=?", (who, a["id"]))
            _event(db, a["id"], "custody_assign", "Custody assigned", who)
    elif act == "custody_return":
        db.execute("UPDATE assets SET custodian='', status='In Stock' WHERE id=?", (a["id"],))
        _event(db, a["id"], "custody_return", "Custody returned", a["custodian"] or "")
    elif act == "move":
        to = request.form.get("site") or a["site"]
        if to != a["site"]:
            _event(db, a["id"], "move", "Asset moved", f"{a['site'] or '—'} → {to}")
            db.execute("UPDATE assets SET site=? WHERE id=?", (to, a["id"]))
    elif act == "maintenance":
        summary = (request.form.get("summary") or "Maintenance").strip()
        try:
            cost = float(request.form.get("cost") or 0)
        except ValueError:
            cost = 0
        set_um = request.form.get("set_status")
        _event(db, a["id"], "maintenance", summary, f"${cost:,.0f}" if cost else "", cost)
        if set_um:
            db.execute("UPDATE assets SET status='Under Maintenance' WHERE id=?", (a["id"],))
    elif act == "status":
        st = request.form.get("status")
        if st in STATUSES and st != a["status"]:
            db.execute("UPDATE assets SET status=? WHERE id=?", (st, a["id"]))
            _event(db, a["id"], "status", f"Status → {st}")

    db.commit()
    log_audit(current_user()["username"], f"asm_{act}", asset_id)
    return redirect(url_for("asm.view", asset_id=asset_id) + "#activity")


@bp.route("/asset/<asset_id>/label")
@permission_required("asm_view")
def label(asset_id):
    db = get_db()
    a = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    if not a:
        abort(404)
    bars = [((sum(bytearray(asset_id.encode())) >> i) & 3) + 1 for i in range(28)]
    return render_template("asm/label.html", a=a, bars=bars)


@bp.route("/asset/<asset_id>/delete", methods=["POST"])
@permission_required("asm_delete")
def delete(asset_id):
    db = get_db()
    a = db.execute("SELECT id FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    if not a:
        abort(404)
    db.execute("DELETE FROM assets WHERE id=?", (a["id"],))  # asset_events cascade via FK
    db.commit()
    log_audit(current_user()["username"], "asm_delete", asset_id)
    return redirect(url_for("asm.index"))


STOCK_CATEGORIES = ["Consumable", "Hardware", "Network", "Power", "Peripheral", "Other"]
WAREHOUSES = ["Central Warehouse", "Head Office", "Textile Factory", "Real Estate Office"]


@bp.route("/stock")
@permission_required("asm_view")
def stock():
    db = get_db()
    items = db.execute("SELECT * FROM stock_items ORDER BY item_code").fetchall()
    return render_template("asm/stock.html", items=items)


@bp.route("/stock/new", methods=["GET", "POST"])
@permission_required("asm_create")
def stock_new():
    db = get_db()
    error = None
    if request.method == "POST":
        code = (request.form.get("item_code") or "").strip().upper()
        if not code or not (request.form.get("name") or "").strip():
            error = "required_fields"
        elif db.execute("SELECT 1 FROM stock_items WHERE item_code=?", (code,)).fetchone():
            error = "item_code_taken"
        if not error:
            db.execute(
                """INSERT INTO stock_items(item_code,name,category,uom,quantity,min_stock,
                   warehouse,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (code, request.form.get("name", "").strip(), request.form.get("category") or "Consumable",
                 request.form.get("uom") or "pcs", int(request.form.get("quantity") or 0),
                 int(request.form.get("min_stock") or 0),
                 request.form.get("warehouse") or "Central Warehouse", utcnow()))
            db.commit()
            log_audit(current_user()["username"], "stock_create", code)
            return redirect(url_for("asm.stock"))
    return render_template("asm/stock_form.html", mode="new", it=None,
                           categories=STOCK_CATEGORIES, warehouses=WAREHOUSES, error=error)


@bp.route("/stock/<code>/edit", methods=["GET", "POST"])
@permission_required("asm_edit")
def stock_edit(code):
    db = get_db()
    it = db.execute("SELECT * FROM stock_items WHERE item_code=?", (code,)).fetchone()
    if not it:
        abort(404)
    if request.method == "POST":
        db.execute(
            """UPDATE stock_items SET name=?, category=?, uom=?, min_stock=?, warehouse=? WHERE id=?""",
            (request.form.get("name", "").strip(), request.form.get("category") or it["category"],
             request.form.get("uom") or it["uom"], int(request.form.get("min_stock") or 0),
             request.form.get("warehouse") or it["warehouse"], it["id"]))
        db.commit()
        log_audit(current_user()["username"], "stock_edit", code)
        return redirect(url_for("asm.stock"))
    return render_template("asm/stock_form.html", mode="edit", it=it,
                           categories=STOCK_CATEGORIES, warehouses=WAREHOUSES, error=None)


@bp.route("/stock/<code>/adjust", methods=["POST"])
@permission_required("asm_edit")
def stock_adjust(code):
    db = get_db()
    it = db.execute("SELECT * FROM stock_items WHERE item_code=?", (code,)).fetchone()
    if not it:
        abort(404)
    try:
        delta = int(request.form.get("delta") or 0)
    except ValueError:
        delta = 0
    if delta:
        newq = max(0, (it["quantity"] or 0) + delta)
        db.execute("UPDATE stock_items SET quantity=? WHERE id=?", (newq, it["id"]))
        db.commit()
        log_audit(current_user()["username"], "stock_adjust", f"{code} {delta:+d} -> {newq}")
    return redirect(url_for("asm.stock"))
