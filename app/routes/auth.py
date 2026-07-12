from flask import (Blueprint, render_template, request, session, redirect,
                   url_for, flash, g)
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_db, log_audit, utcnow
from app.auth import current_user
from app.security import ROLE_LABELS
from config import Config

bp = Blueprint("auth", __name__)


def _safe_next(nxt):
    return nxt if (nxt and nxt.startswith("/") and not nxt.startswith("//")) else None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.dashboard"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = get_db().execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["uid"] = row["id"]
            session.permanent = True
            if row["lang_pref"]:
                session["lang"] = row["lang_pref"]
            log_audit(username, "login", ip=request.remote_addr or "")
            return redirect(_safe_next(request.args.get("next")) or url_for("main.dashboard"))
        error = "invalid_credentials"
    return render_template("login.html", error=error, allow_signup=Config.ALLOW_SIGNUP)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if not Config.ALLOW_SIGNUP:
        return redirect(url_for("auth.login"))
    if current_user():
        return redirect(url_for("main.dashboard"))
    db = get_db()
    error = None
    # New self-service accounts always get the lowest, non-privileged role.
    role = Config.SIGNUP_ROLE if Config.SIGNUP_ROLE in ROLE_LABELS else "employee"
    if role in ("super_admin", "it_admin"):
        role = "employee"
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        pw = request.form.get("password") or ""
        if not username or not full_name:
            error = "required_fields"
        elif not username.replace("_", "").replace(".", "").isalnum():
            error = "username_invalid"
        elif len(pw) < 8:
            error = "password_too_short"
        elif db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            error = "username_taken"
        if not error:
            db.execute(
                """INSERT INTO users(username,password_hash,full_name,email,role,department,
                   site,lang_pref,theme_pref,is_active,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
                (username, generate_password_hash(pw), full_name,
                 email or f"{username}@tgroup.local", role, "General", "Head Office",
                 session.get("lang", "en"), session.get("theme", "dark"), utcnow()))
            row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            db.commit()
            log_audit(username, "signup", ip=request.remote_addr or "")
            session.clear()
            session["uid"] = row["id"]
            session.permanent = True
            return redirect(url_for("main.dashboard"))
    return render_template("signup.html", error=error, role_label=ROLE_LABELS.get(role, "Employee"))


@bp.route("/logout", methods=["POST"])
def logout():
    u = current_user()
    if u:
        log_audit(u["username"], "logout", ip=request.remote_addr or "")
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/set-lang/<lang>", methods=["POST"])
def set_lang(lang):
    if lang in Config.LANGUAGES:
        session["lang"] = lang
        u = current_user()
        if u:
            db = get_db()
            db.execute("UPDATE users SET lang_pref=? WHERE id=?", (lang, u["id"]))
            db.commit()
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.route("/set-theme/<theme>", methods=["POST"])
def set_theme(theme):
    if theme in ("dark", "light"):
        session["theme"] = theme
        u = current_user()
        if u:
            db = get_db()
            db.execute("UPDATE users SET theme_pref=? WHERE id=?", (theme, u["id"]))
            db.commit()
    return redirect(request.referrer or url_for("main.dashboard"))
