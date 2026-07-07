#!/usr/bin/env python3
"""T-CAP Monitoring Agent.

Collects host metrics and reports them to the T-CAP ingestion API on an interval.
Enroll the device in the web UI (03 Monitoring -> Enroll device) to get a token,
put it in agent_config.json, then run:  python tcap_agent.py

Uses psutil when available for accurate metrics; otherwise falls back to Windows
stdlib (ctypes / wmic / shutil) so it runs on a bare Python install.
"""
import json
import os
import sys
import time
import shutil
import platform
import urllib.request
import urllib.error

AGENT_VERSION = "1.4.0"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "agent_config.json")
QUEUE_PATH = os.path.join(HERE, "pending.jsonl")

try:
    import psutil  # accurate metrics if present
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False


def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(f"Missing {CONFIG_PATH}. Copy agent_config.example.json and fill it in.")
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    for k in ("server_url", "hostname", "token"):
        if not cfg.get(k):
            sys.exit(f"agent_config.json is missing '{k}'.")
    cfg.setdefault("interval_seconds", 30)
    cfg.setdefault("disk_path", "C:\\" if os.name == "nt" else "/")
    cfg["server_url"] = cfg["server_url"].rstrip("/")
    return cfg


# ---- metric collection (psutil or stdlib fallback) ------------------------
def _ram_percent_win():
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return float(st.dwMemoryLoad)


def _cpu_percent_win():
    try:
        import subprocess
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "loadpercentage", "/value"],
            stderr=subprocess.DEVNULL, timeout=6).decode(errors="ignore")
        for line in out.splitlines():
            if "LoadPercentage" in line:
                return float(line.split("=")[1].strip())
    except Exception:
        pass
    return 0.0


def _uptime_hours_win():
    try:
        import ctypes
        return round(ctypes.windll.kernel32.GetTickCount64() / 1000 / 3600, 1)
    except Exception:
        return 0.0


def collect(cfg):
    if HAS_PSUTIL:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage(cfg["disk_path"]).percent
        uptime = round((time.time() - psutil.boot_time()) / 3600, 1)
    else:
        cpu = _cpu_percent_win() if os.name == "nt" else 0.0
        ram = _ram_percent_win() if os.name == "nt" else 0.0
        try:
            u = shutil.disk_usage(cfg["disk_path"])
            disk = round(u.used / u.total * 100, 1)
        except Exception:
            disk = 0.0
        uptime = _uptime_hours_win() if os.name == "nt" else 0.0
    return {
        "hostname": cfg["hostname"], "token": cfg["token"],
        "cpu": round(cpu, 1), "ram": round(ram, 1), "disk": round(disk, 1),
        "uptime_h": uptime, "agent_ver": AGENT_VERSION,
        "os": platform.platform(),
    }


# ---- reporting with offline queue -----------------------------------------
def post(cfg, payload):
    url = cfg["server_url"] + "/api/agent/metrics"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "X-Agent-Token": cfg["token"]})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _queue(payload):
    try:
        with open(QUEUE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def _flush_queue(cfg):
    if not os.path.exists(QUEUE_PATH):
        return
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        remaining = []
        for ln in lines:
            try:
                post(cfg, json.loads(ln))
            except Exception:
                remaining.append(ln)
        if remaining:
            with open(QUEUE_PATH, "w", encoding="utf-8") as fh:
                fh.write("\n".join(remaining) + "\n")
        else:
            os.remove(QUEUE_PATH)
    except Exception:
        pass


def main():
    cfg = load_config()
    print(f"T-CAP agent v{AGENT_VERSION} · host={cfg['hostname']} · "
          f"server={cfg['server_url']} · psutil={'yes' if HAS_PSUTIL else 'no (fallback)'}")
    once = "--once" in sys.argv
    while True:
        payload = collect(cfg)
        try:
            _flush_queue(cfg)
            res = post(cfg, payload)
            print(f"[{time.strftime('%H:%M:%S')}] sent cpu={payload['cpu']} ram={payload['ram']} "
                  f"disk={payload['disk']} -> status={res.get('status')}")
        except urllib.error.HTTPError as e:
            print(f"[{time.strftime('%H:%M:%S')}] server rejected ({e.code}) — check token/hostname")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] offline ({e}); queued")
            _queue(payload)
        if once:
            break
        time.sleep(cfg["interval_seconds"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.")
