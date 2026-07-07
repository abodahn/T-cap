from flask import (Blueprint, render_template, request, session, redirect,
                   url_for, flash, g)
from werkzeug.security import check_password_hash

from app.db import get_db, log_audit
from app.auth import current_user
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
    return render_template("login.html", error=error)


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
