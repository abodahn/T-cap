# T-CAP — T-Group Enterprise Control Suite

One bilingual (English + Arabic/RTL) command center over three connected systems, in
the T-Group premium monochrome brand:

- **01 · ITSM Command Center** — tickets, priority/SLA, assignment, activity timeline
- **02 · Asset & Stock** — asset register, custody, stock levels, warranty
- **03 · Monitoring & Risk** — endpoint health, alerts, one-click alert → ITSM ticket

Plus a shared platform: executive dashboard, global search, notifications, reports,
role-based access control (10 roles), audit log, and per-user language + theme.

## Quick start (Windows / PowerShell)

```powershell
cd D:\T-CAP\t-cap
pip install -r requirements.txt          # first time only
$env:TCAP_COOKIE_SECURE="false"          # allow login over plain HTTP locally
python run.py
```
Open **http://127.0.0.1:8080**.

On first run an admin is created and a **one-time password is printed to the console**
(unless you set `TCAP_ADMIN_PASSWORD`). Sample role accounts are also seeded
(`TCAP_SEED_DEMO=true`), password **`Demo@2026`**:

| Login | Role |
|-------|------|
| `admin` | Super Admin |
| `itadmin` | IT Admin |
| `agent` | IT Agent |
| `assets` | Asset Manager |
| `stock` | Stock Controller |
| `monitor` | Monitoring Admin |
| `exec` | Executive |
| `auditor` | Auditor (read-only) |
| `employee` | Employee |

Use the top-bar buttons to switch **language (EN ⇄ ع)** and **theme (dark ⇄ light)**.

## Security defaults
- No hard-coded passwords; admin password is random unless you set `TCAP_ADMIN_PASSWORD`.
- Strong secret key auto-generated and persisted to `instance/.secret_key`.
- CSRF protection on every form; secure/HttpOnly session cookies (Secure on by default —
  set `TCAP_COOKIE_SECURE=false` only for local HTTP).
- RBAC enforced on every route; security headers on every response; audit log.

## Configuration
Copy `.env.example` to `.env`. Everything has a safe default — see that file for options.

## Production
```
waitress-serve --host 0.0.0.0 --port 8080 --call app:create_app     # Windows
gunicorn "app:create_app()" -b 0.0.0.0:8080                          # Linux
```
Set `TCAP_ENV=production`, a strong `TCAP_ADMIN_PASSWORD`, `TCAP_SEED_DEMO=false`,
and keep `TCAP_COOKIE_SECURE=true` behind HTTPS.

## Layout
```
t-cap/
  run.py  config.py  requirements.txt  .env.example
  app/
    __init__.py        app factory, nav, security headers, i18n context
    db.py              sqlite schema + seed (no ORM, stdlib only)
    security.py        roles & permissions
    auth.py  csrf.py  i18n.py
    routes/            auth, main, itsm, asm, monitoring, admin
    templates/         base shell + login + per-module pages
    static/css/        tc-brand.css (brand system) + app.css
    static/i18n/       en.json, ar.json
    static/img/        T-Group logo kit + favicons
  instance/            tcap.db + .secret_key (auto-created, git-ignored)
```

## Brand
The monochrome design system lives in `app/static/css/tc-brand.css` — exact T-Group
greys (`#3C3C3C` charcoal, `#7E8080` grey), Arial typography, thin dividers, `01/02/03`
numerals, and the charcoal radial hero. Color appears only for status/severity.
