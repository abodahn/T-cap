"""ITSM domain core — statuses, priority matrix, SLA policy and live SLA math.
Shared by the seed (db.py) and the routes so the rules live in one place."""
from datetime import datetime, timedelta, timezone

TYPES = ["Incident", "Service Request", "Change", "Access", "Hardware",
         "Software", "Network", "ERP", "Security", "Other"]

# category -> subcategories
CATEGORIES = {
    "Hardware": ["Laptop/Desktop", "Printer", "Peripheral", "Server", "Other"],
    "Software": ["Application", "Operating System", "ERP/SAP", "Email", "License"],
    "Network": ["Wi-Fi", "VPN", "Connectivity", "Firewall"],
    "Access": ["Account/Password", "Permissions", "Shared Drive", "Onboarding"],
    "Infrastructure": ["Power/UPS", "Cooling", "Data Center", "Cabling"],
    "Other": ["General"],
}

STATUSES = ["New", "Assigned", "In Progress", "Waiting User", "Waiting Vendor",
            "On Hold", "Resolved", "Closed", "Reopened", "Cancelled"]
OPEN_STATUSES = ["New", "Assigned", "In Progress", "Reopened"]
PAUSED_STATUSES = ["Waiting User", "Waiting Vendor", "On Hold"]      # SLA clock stops
CLOSED_STATUSES = ["Resolved", "Closed", "Cancelled"]

CLOSURE_CATEGORIES = ["Resolved Permanently", "Workaround", "No Action Required",
                      "Duplicate", "User Error", "Cancelled by User"]

IMPACTS = ["Single User", "Multiple Users", "Department", "Whole Company"]
URGENCIES = ["Low", "Medium", "High", "Critical"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]

# Impact (rows) x Urgency (cols) -> Priority. Classic ITIL 4x4 matrix.
_M = {
    "Single User":   {"Low": "Low",    "Medium": "Low",    "High": "Medium",   "Critical": "High"},
    "Multiple Users":{"Low": "Low",    "Medium": "Medium", "High": "High",     "Critical": "High"},
    "Department":    {"Low": "Medium", "Medium": "High",   "High": "High",     "Critical": "Critical"},
    "Whole Company": {"Low": "High",   "Medium": "High",   "High": "Critical", "Critical": "Critical"},
}


def derive_priority(impact, urgency):
    return _M.get(impact, _M["Single User"]).get(urgency, "Medium")


# minutes, per priority
RESPONSE_MIN = {"Critical": 15, "High": 30, "Medium": 120, "Low": 480}
RESOLUTION_MIN = {"Critical": 240, "High": 480, "Medium": 1440, "Low": 4320}
WARNING_PCT = 75


def _parse(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fmt_minutes(m):
    m = int(round(m))
    sign = "-" if m < 0 else ""
    m = abs(m)
    if m >= 1440:
        return f"{sign}{m // 1440}d {(m % 1440) // 60}h"
    if m >= 60:
        return f"{sign}{m // 60}h {m % 60}m"
    return f"{sign}{m}m"


def compute_sla(ticket, now=None):
    """Live SLA state (computed on read — no scheduler). Returns a dict."""
    now = now or datetime.now(timezone.utc)
    status = ticket["status"]
    created = _parse(ticket["created_at"])
    res_due = _parse(ticket["sla_due"])            # resolution due
    resp_due = _parse(ticket["response_due"]) if "response_due" in ticket.keys() else None
    resolved = _parse(ticket["resolved_at"])
    first_resp = _parse(ticket["first_response_at"]) if "first_response_at" in ticket.keys() else None

    out = {"status": "Within SLA", "percent": 0, "remaining": "", "remaining_min": 0,
           "response": "pending", "breached": False, "paused": False}

    # response SLA
    if first_resp:
        out["response"] = "breached" if (resp_due and first_resp > resp_due) else "met"
    elif resp_due and now > resp_due and status not in CLOSED_STATUSES:
        out["response"] = "breached"

    if status in CLOSED_STATUSES:
        end = resolved or now
        if res_due and created:
            total = (res_due - created).total_seconds() / 60 or 1
            used = (end - created).total_seconds() / 60
            out["percent"] = max(0, min(100, round(used / total * 100)))
        out["status"] = "Breached" if (res_due and end and end > res_due) else "Met"
        return out

    if status in PAUSED_STATUSES:
        out["status"] = "Paused"
        out["paused"] = True

    if res_due and created:
        total = (res_due - created).total_seconds() / 60 or 1
        used = (now - created).total_seconds() / 60
        pct = round(used / total * 100)
        out["percent"] = max(0, min(100, pct))
        out["remaining_min"] = int((res_due - now).total_seconds() / 60)
        out["remaining"] = fmt_minutes(out["remaining_min"])
        if not out["paused"]:
            if now > res_due:
                out["status"] = "Breached"
                out["breached"] = True
            elif pct >= WARNING_PCT:
                out["status"] = "Warning"
    return out


def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def due_str(minutes, base=None):
    base = base or datetime.now(timezone.utc)
    return (base + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
