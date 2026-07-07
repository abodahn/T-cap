import secrets

from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from werkzeug.security import generate_password_hash

from app.db import get_db, utcnow, log_audit
from app.auth import permission_required, current_user
from app import security as sec
from app import rbac

bp = Blueprint("admin", __name__, url_prefix="/admin")

DEPARTMENTS = ["IT", "IT Security", "Facilities", "Warehouse", "Production",
               "Executive", "Internal Audit", "Finance", "HR", "Operations"]
SITES = ["Head Office", "Textile Factory", "Central Warehouse", "Real Estate Office"]


@bp.route("/")
@bp.route("/users")
@permission_required("admin_access")
def users():
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY role, username").fetchall()
    audit = db.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 20").fetchall()
    return render_template("admin/users.html", users=rows, roles=sec.ROLE_LABELS, audit=audit)


@bp.route("/users/new", methods=["GET", "POST"])
@permission_required("manage_users")
def user_new():
    db = get_db()
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        full_name = (request.form.get("full_name") or "").strip()
        role = request.form.get("role") or "employee"
        pw = request.form.get("password") or ""
        gen = False
        if not username or not full_name:
            error = "required_fields"
        elif role not in sec.ROLE_LABELS:
            error = "invalid_role"
        elif role == "super_admin" and current_user()["role"] != "super_admin":
            # Only a super admin may create another super admin (privilege escalation guard).
            error = "cannot_assign_superadmin"
        elif db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            error = "username_taken"
        if not error:
            if len(pw) < 6:
                pw = secrets.token_urlsafe(9)
                gen = True
            db.execute(
                """INSERT INTO users(username,password_hash,full_name,email,role,department,
                   site,lang_pref,theme_pref,is_active,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
                (username, generate_password_hash(pw), full_name,
                 request.form.get("email") or f"{username}@tgroup.local", role,
                 request.form.get("department") or "Operations",
                 request.form.get("site") or "Head Office", "en", "dark", utcnow()))
            db.commit()
            log_audit(current_user()["username"], "user_create", username)
            if gen:
                flash(f"created:{username}:{pw}")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", mode="new", u=None, roles=sec.ROLE_LABELS,
                           departments=DEPARTMENTS, sites=SITES, error=error)


@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@permission_required("manage_users")
def user_edit(uid):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        abort(404)
    if request.method == "POST":
        role = request.form.get("role") or u["role"]
        if u["role"] == "super_admin":
            role = "super_admin"  # never demote the last super admin here
        elif role == "super_admin" and current_user()["role"] != "super_admin":
            role = u["role"]  # only a super admin may elevate someone to super admin
        # A super admin must never be deactivated here (its is_active checkbox is
        # disabled in the form, so it wouldn't post — which previously locked it out).
        is_active = 1 if (u["role"] == "super_admin" or request.form.get("is_active")) else 0
        db.execute("""UPDATE users SET full_name=?, email=?, role=?, department=?, site=?,
                      is_active=? WHERE id=?""",
                   (request.form.get("full_name") or u["full_name"],
                    request.form.get("email") or u["email"], role,
                    request.form.get("department") or u["department"],
                    request.form.get("site") or u["site"], is_active, uid))
        newpw = request.form.get("password") or ""
        if len(newpw) >= 6:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(newpw), uid))
        db.commit()
        log_audit(current_user()["username"], "user_edit", u["username"])
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", mode="edit", u=u, roles=sec.ROLE_LABELS,
                           departments=DEPARTMENTS, sites=SITES, error=None)


@bp.route("/users/<int:uid>/toggle", methods=["POST"])
@permission_required("manage_users")
def toggle_user(uid):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        abort(404)
    if u["role"] == "super_admin":
        return redirect(url_for("admin.users"))
    db.execute("UPDATE users SET is_active=? WHERE id=?", (0 if u["is_active"] else 1, uid))
    db.commit()
    log_audit(current_user()["username"], "toggle_user", u["username"])
    return redirect(url_for("admin.users"))


@bp.route("/roles")
@permission_required("admin_access")
def roles():
    db = get_db()
    grant = {}
    for row in db.execute("SELECT role, perm FROM role_perms").fetchall():
        grant.setdefault(row["role"], set()).add(row["perm"])
    # responsibility matrix: role -> module -> level
    resp = {}
    for r in sec.ROLE_LABELS:
        perms = grant.get(r, set())
        resp[r] = {}
        for mod, (full, view) in sec.MODULE_PERMS.items():
            if full and full in perms:
                resp[r][mod] = "full"
            elif view in perms:
                resp[r][mod] = "view"
            else:
                resp[r][mod] = "none"
    counts = {r: db.execute("SELECT COUNT(*) FROM users WHERE role=?", (r,)).fetchone()[0] for r in sec.ROLE_LABELS}
    return render_template("admin/roles.html", groups=sec.PERMISSION_GROUPS,
                           plabels=sec.PERMISSION_LABELS, roles=sec.ROLE_LABELS,
                           grant=grant, can_edit=(current_user() and current_user()["role"] == "super_admin"),
                           resp=resp, modules=list(sec.MODULE_PERMS.keys()), counts=counts)


@bp.route("/roles/save", methods=["POST"])
@permission_required("manage_settings")
def roles_save():
    if current_user()["role"] != "super_admin":
        abort(403)
    db = get_db()
    all_perms = set(sec.PERMISSIONS)
    for role in sec.ROLE_LABELS:
        if role == "super_admin":
            continue  # always full
        db.execute("DELETE FROM role_perms WHERE role=?", (role,))
        for perm in all_perms:
            if request.form.get(f"p:{role}:{perm}"):
                db.execute("INSERT OR IGNORE INTO role_perms(role,perm) VALUES(?,?)", (role, perm))
    # guarantee super_admin keeps everything
    db.execute("DELETE FROM role_perms WHERE role='super_admin'")
    for perm in all_perms:
        db.execute("INSERT OR IGNORE INTO role_perms(role,perm) VALUES('super_admin',?)", (perm,))
    db.commit()
    rbac.invalidate()
    log_audit(current_user()["username"], "roles_save", "permissions updated")
    return redirect(url_for("admin.roles"))
