# Deploying T-CAP to Render

T-CAP ships ready for [Render](https://render.com). It runs under gunicorn and,
on the free plan, uses an auto-seeded SQLite database (a fully-populated demo on
every boot). For persistence across deploys, use a paid plan with a disk (below).

## Option A — Blueprint (recommended, one click)

1. Push this folder to a GitHub repo (see **Push to GitHub** below).
2. In Render: **New → Blueprint**, select your repo. Render reads `render.yaml`
   and creates the web service with all settings and generated secrets.
3. Click **Apply**. First build takes ~2–3 minutes.
4. Open **Environment** on the new service and copy the generated
   **`TCAP_ADMIN_PASSWORD`** — that's your `admin` login.
5. Visit `https://<your-service>.onrender.com`.

## Option B — Manual web service

1. **New → Web Service**, connect the repo.
2. Settings:
   - **Runtime:** Python
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn wsgi:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT`
   - **Health check path:** `/healthz`
3. Add environment variables:
   | Key | Value |
   |-----|-------|
   | `TCAP_ENV` | `production` |
   | `TCAP_SECRET_KEY` | *(a long random string)* |
   | `TCAP_ADMIN_PASSWORD` | *(a strong password — your `admin` login)* |
   | `TCAP_COOKIE_SECURE` | `true` |
   | `TCAP_SEED_DEMO` | `true` (demo) / `false` (private) |
   | `PYTHON_VERSION` | `3.12.5` |
4. Create the service.

## Push to GitHub

From this `t-cap` folder (a git repo is already initialized):

```bash
git add -A
git commit -m "T-CAP deploy"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

## Logins

- **admin** / the `TCAP_ADMIN_PASSWORD` you set (or the generated one in the
  Render Environment tab). If neither is set, a random one is printed **once** in
  the deploy logs.
- Demo role accounts (when `TCAP_SEED_DEMO=true`), password **`Demo@2026`**:
  `itadmin`, `agent`, `assets`, `stock`, `monitor`, `exec`, `auditor`, `employee`.

## Data persistence

- **Free plan:** the filesystem is ephemeral — the SQLite DB is re-created and
  re-seeded on every deploy/restart. Great for a demo; data does not persist.
- **Persist across deploys (paid plan):** in `render.yaml`, uncomment the `disk:`
  block and the `TCAP_DB_PATH` env var (`/var/data/tcap.db`), then redeploy. The
  DB then lives on a real disk and survives deploys.

## Email notifications (optional)

Set `TCAP_SMTP_HOST`, `TCAP_SMTP_PORT`, `TCAP_SMTP_USER`, `TCAP_SMTP_PASS`,
`TCAP_ALERT_EMAILS`, and `TCAP_PUBLIC_URL` to enable SLA-breach / stock-low /
assignment emails. Left unset, notifications stay in-app only.

## The monitoring agent against a Render deploy

Enroll a device in the UI, then set the agent's `server_url` to your Render URL
(`https://<service>.onrender.com`) in `agent/agent_config.json`. See `agent/README.md`.
Note: free-plan services sleep after 15 min idle; the agent's first post wakes it.
