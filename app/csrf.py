"""Lightweight per-session CSRF protection (no external deps)."""
import secrets

from flask import session, request, abort

_SAFE = {"GET", "HEAD", "OPTIONS", "TRACE"}


def get_token():
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["_csrf"] = tok
    return tok


def protect():
    """before_request hook: validate token on state-changing requests."""
    if request.method in _SAFE:
        return
    # Agent ingestion API is token-authenticated, not a browser form.
    if request.path.startswith("/api/agent/"):
        return
    sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
    if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
        abort(400, description="Invalid or missing CSRF token")
