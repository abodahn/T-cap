"""T-CAP — T-Group Enterprise Control Suite: central configuration.

All secrets come from the environment. Secure by default: no debug, no known
default passwords, strong auto-generated secret key.
"""
import os
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

_INSECURE = {"", "change-me", "changeme", "secret", "dev", "dev-secret",
             "tc-cap-dev-secret-change-me"}
_WEAK_PW = {"", "admin", "admin123", "password", "changeme", "change-me",
            "secret", "123456", "admin@12345", "admin@1122"}


def _bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on", "y"}


def _resolve_secret_key():
    env = (os.getenv("TCAP_SECRET_KEY") or "").strip()
    if env and env.lower() not in _INSECURE:
        return env
    keyfile = INSTANCE_DIR / ".secret_key"
    try:
        if keyfile.exists():
            saved = keyfile.read_text(encoding="utf-8").strip()
            if saved:
                return saved
        gen = secrets.token_hex(32)
        keyfile.write_text(gen, encoding="utf-8")
        try:
            os.chmod(keyfile, 0o600)
        except Exception:
            pass
        return gen
    except Exception:
        return secrets.token_hex(32)


class Config:
    ENV = os.getenv("TCAP_ENV", "development")
    IS_PRODUCTION = ENV.lower() == "production"
    SECRET_KEY = _resolve_secret_key()
    DEBUG = _bool(os.getenv("TCAP_DEBUG"), False)
    HOST = os.getenv("TCAP_HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", os.getenv("TCAP_PORT", "8080")))

    DB_PATH = Path(os.getenv("TCAP_DB_PATH", str(INSTANCE_DIR / "tcap.db")))

    # Session cookie: Secure by default (HTTPS/prod). For plain-HTTP local
    # testing set TCAP_COOKIE_SECURE=false.
    COOKIE_SECURE = _bool(os.getenv("TCAP_COOKIE_SECURE"), True)
    COOKIE_SAMESITE = os.getenv("TCAP_COOKIE_SAMESITE", "Lax")
    SESSION_MINUTES = int(os.getenv("TCAP_SESSION_MINUTES", "180"))

    # Admin bootstrap — random one-time password if none supplied (printed once).
    ADMIN_USER = os.getenv("TCAP_ADMIN_USER", "admin")
    _admin_pw = (os.getenv("TCAP_ADMIN_PASSWORD") or "").strip()
    ADMIN_PASSWORD_FROM_ENV = bool(_admin_pw) and _admin_pw.lower() not in _WEAK_PW
    ADMIN_PASSWORD = _admin_pw if ADMIN_PASSWORD_FROM_ENV else secrets.token_urlsafe(9)

    # Demo/sample users (director, agent, ... shared password). Off unless asked.
    SEED_DEMO = _bool(os.getenv("TCAP_SEED_DEMO"), True)  # default on for a fresh eval build
    DEMO_PASSWORD = os.getenv("TCAP_DEMO_PASSWORD", "Demo@2026")

    # i18n
    DEFAULT_LANG = os.getenv("TCAP_DEFAULT_LANG", "en")
    LANGUAGES = ("en", "ar")
    DEFAULT_THEME = os.getenv("TCAP_DEFAULT_THEME", "dark")  # dark | light

    MAX_CONTENT_LENGTH = int(os.getenv("TCAP_MAX_UPLOAD_MB", "12")) * 1024 * 1024
    ORG_NAME = os.getenv("TCAP_ORG_NAME", "T-GROUP")

    # --- Email (SMTP) for notifications. Blank host = email disabled (in-app only). ---
    SMTP_HOST = (os.getenv("TCAP_SMTP_HOST", "") or "").strip()
    SMTP_PORT = int(os.getenv("TCAP_SMTP_PORT", "587"))
    SMTP_USER = (os.getenv("TCAP_SMTP_USER", "") or "").strip()
    SMTP_PASS = os.getenv("TCAP_SMTP_PASS", "") or ""
    SMTP_FROM = (os.getenv("TCAP_SMTP_FROM", "") or os.getenv("TCAP_SMTP_USER", "")
                 or "tcap@tgroup.local").strip()
    SMTP_TLS = _bool(os.getenv("TCAP_SMTP_TLS"), True)
    # Public base URL so notification emails can link back (e.g. http://host:8080)
    PUBLIC_URL = (os.getenv("TCAP_PUBLIC_URL", "") or "").strip().rstrip("/")
    # Fallback recipients for broadcast alerts (SLA breach, stock-low) when no
    # specific user email is known. Comma-separated.
    ALERT_EMAILS = [e.strip() for e in (os.getenv("TCAP_ALERT_EMAILS", "") or "").split(",") if e.strip()]
