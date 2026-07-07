"""Local preview runner (for screenshots / design review). Not used in production."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)
sys.path.insert(0, _HERE)

os.environ.setdefault("TCAP_COOKIE_SECURE", "false")
os.environ.setdefault("TCAP_SAMESITE", "Lax")
os.environ.setdefault("TCAP_ADMIN_PASSWORD", "Preview@2026")
os.environ.setdefault("TCAP_SEED_DEMO", "true")
os.environ.setdefault("TCAP_DEBUG", "false")

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("TCAP_PORT", "8091")))
    app.run(host="127.0.0.1", port=port, debug=False)
