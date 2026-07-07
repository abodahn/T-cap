# T-CAP Monitoring Agent

A lightweight agent that reports host metrics (CPU, RAM, disk, uptime) to the
T-CAP ingestion API. It works with `psutil` (accurate) or falls back to Windows
stdlib so it runs on a bare Python install.

## 1. Enroll the device (in the web UI)
Open **T-CAP → 03 Monitoring → ＋ Enroll device**, enter the hostname/IP/site, and
submit. You'll get a **one-time token** — copy it (it's shown once, stored hashed).

## 2. Configure the agent (on the device)
```
copy agent_config.example.json agent_config.json
```
Edit `agent_config.json`:
- `server_url` — where T-CAP is reachable, e.g. `http://10.0.0.5:8080`
- `hostname` — must match the enrolled hostname exactly
- `token` — the enrollment token
- `interval_seconds` — how often to report (default 30)

## 3. Install dependencies (recommended)
```
pip install -r requirements.txt
```
(Skip this and the agent still runs, using a Windows stdlib fallback.)

## 4. Run
One-shot test (send a single report and exit):
```
python tcap_agent.py --once
```
Continuous:
```
python tcap_agent.py
```
You should see the endpoint go **online** in the dashboard with live metrics, and
alerts appear automatically when a metric crosses a rule threshold
(**Monitoring → Alert rules**).

## 5. Run as a service (starts at boot, auto-restarts)
Elevated PowerShell, from this folder:
```
powershell -ExecutionPolicy Bypass -File .\install_agent.ps1
```
Remove it with:
```
Unregister-ScheduledTask -TaskName TCAP-Monitoring-Agent -Confirm:$false
```

## Optional — build a single .exe
```
pip install pyinstaller
pyinstaller --onefile --name tcap-agent tcap_agent.py
```
Ship `dist\tcap-agent.exe` alongside `agent_config.json`.

## How it reports
`POST {server_url}/api/agent/metrics` with header `X-Agent-Token: <token>` and a
JSON body `{hostname, cpu, ram, disk, uptime_h, agent_ver}`. Offline reports are
queued to `pending.jsonl` and flushed on the next successful connection.
