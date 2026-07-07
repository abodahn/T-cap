"""Authentication & authorization helpers."""
from functools import wraps

from flask import g, session, redirect, url_for, request, abort

from app.db import get_db
from app.rbac import role_can


def current_user():
    if "user" in g:
        return g.user
    uid = session.get("uid")
    g.user = None
    if uid:
        row = get_db().execute(
            "SELECT * FROM users WHERE id=? AND is_active=1", (uid,)).fetchone()
        g.user = row
    return g.user


def user_can(perm):
    u = current_user()
    return bool(u) and role_can(u["role"], perm)


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not current_user():
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def permission_required(perm):
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if not current_user():
                return redirect(url_for("auth.login", next=request.path))
            if not user_can(perm):
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco
