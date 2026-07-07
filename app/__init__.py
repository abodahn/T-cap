import datetime as _dt

from flask import Flask, session, g, render_template, request

from config import Config
from app import db as dbm
from app.auth import current_user, user_can
from app.i18n import translate, get_lang, is_rtl
from app import csrf as csrfmod
from app import charts as chartmod
from app import masterdata

# Status → color (only place saturated color enters charts)
STATUS_COLORS = {
    "Critical": "var(--status-danger)", "High": "var(--status-warning)",
    "Medium": "var(--brand-grey)", "Low": "var(--brand-silver)",
    "New": "var(--status-info)", "Assigned": "var(--status-info)",
    "In Progress": "var(--status-warning)", "Pending": "var(--status-warning)",
    "Resolved": "var(--status-success)", "Closed": "var(--brand-grey)",
    "Reopened": "var(--status-danger)",
    "online": "var(--status-success)", "warning": "var(--status-warning)",
    "offline": "var(--status-danger)",
}


# Sidebar navigation: (key, endpoint, icon-number, permission)
NAV_SYSTEMS = [
    ("itsm", "itsm.index", "01", "itsm_view"),
    ("asm", "asm.index", "02", "asm_view"),
    ("monitoring", "monitoring.index", "03", "mon_view"),
]
NAV_PLATFORM = [
    ("dashboard", "main.dashboard", "◆", "view_dashboard"),
    ("workspace", "main.workspace", "◆", "itsm_edit"),
    ("reports", "main.reports", "◆", "reports_view"),
    ("admin", "admin.users", "◆", "admin_access"),
]


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=Config.SECRET_KEY,
        MAX_CONTENT_LENGTH=Config.MAX_CONTENT_LENGTH,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=Config.COOKIE_SECURE,
        SESSION_COOKIE_SAMESITE=Config.COOKIE_SAMESITE,
        PERMANENT_SESSION_LIFETIME=_dt.timedelta(minutes=Config.SESSION_MINUTES),
        JSON_AS_ASCII=False,
    )

    dbm.init_db()
    app.teardown_appcontext(dbm.close_db)

    @app.before_request
    def _csrf():
        return csrfmod.protect()

    @app.after_request
    def _headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return resp

    @app.context_processor
    def _inject():
        lang = get_lang()
        return dict(
            t=translate, lang=lang, is_rtl=is_rtl(lang),
            dir_="rtl" if is_rtl(lang) else "ltr",
            user=current_user(), user_can=user_can,
            nav_systems=NAV_SYSTEMS, nav_platform=NAV_PLATFORM,
            csrf_token=csrfmod.get_token, org=Config.ORG_NAME,
            theme=(session.get("theme")
                   or (current_user()["theme_pref"] if current_user() else None)
                   or Config.DEFAULT_THEME),
            year=_dt.datetime.now().year,
            donut=chartmod.donut, gauge=chartmod.gauge,
            sparkline=chartmod.sparkline, hbars=chartmod.hbars,
            status_colors=STATUS_COLORS, md=masterdata.as_dict(),
        )

    from app.routes.auth import bp as auth_bp
    from app.routes.main import bp as main_bp
    from app.routes.itsm import bp as itsm_bp
    from app.routes.asm import bp as asm_bp
    from app.routes.monitoring import bp as mon_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.agent_api import bp as agent_bp
    for bp in (auth_bp, main_bp, itsm_bp, asm_bp, mon_bp, admin_bp, agent_bp):
        app.register_blueprint(bp)

    @app.errorhandler(403)
    def _403(e):
        return render_template("error.html", code=403, msg="forbidden"), 403

    @app.errorhandler(404)
    def _404(e):
        return render_template("error.html", code=404, msg="not_found"), 404

    @app.errorhandler(400)
    def _400(e):
        return render_template("error.html", code=400,
                               msg=getattr(e, "description", "bad_request")), 400

    return app
