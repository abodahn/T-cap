"""DB-backed RBAC. Permissions per role live in the `role_perms` table (seeded
from security.ROLES), so an admin can edit them and it takes effect immediately.
Loaded once per request onto flask.g. Falls back to the static defaults if the
table is empty or unavailable."""
from flask import g

from app.db import get_db
from app.security import ROLES, PERMISSIONS, DEFAULT_ROLE


def _static():
    m = {}
    for r, ps in ROLES.items():
        m[r] = set(PERMISSIONS) if "*" in ps else set(ps)
    return m


def load():
    if "_rbac" in g:
        return g._rbac
    m = {}
    try:
        for row in get_db().execute("SELECT role, perm FROM role_perms").fetchall():
            m.setdefault(row["role"], set()).add(row["perm"])
    except Exception:
        m = {}
    if not m:
        m = _static()
    g._rbac = m
    return m


def role_can(role, perm):
    m = load()
    perms = m.get(role)
    if perms is None:
        perms = m.get(DEFAULT_ROLE, set())
    return perm in perms


def role_perms(role):
    return load().get(role, set())


def invalidate():
    g.pop("_rbac", None)
