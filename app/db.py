"""T-CAP persistence — stdlib sqlite3, no ORM. Schema + idempotent seed."""
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import g
from werkzeug.security import generate_password_hash

from config import Config
from app.security import ROLE_LABELS


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(str(Config.DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, name_en TEXT, name_ar TEXT);
CREATE TABLE IF NOT EXISTS sites(
  id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, name_en TEXT,
  name_ar TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT,
  full_name TEXT, email TEXT, role TEXT, department TEXT, site TEXT,
  lang_pref TEXT DEFAULT 'en', theme_pref TEXT DEFAULT 'dark',
  is_active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, detail TEXT,
  ip TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, severity TEXT, module TEXT, title TEXT,
  message TEXT, link TEXT, target_user TEXT, ext_key TEXT,
  is_read INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS role_perms(role TEXT, perm TEXT, PRIMARY KEY(role,perm));

CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, subject TEXT,
  description TEXT, type TEXT, category TEXT, subcategory TEXT, priority TEXT,
  impact TEXT, urgency TEXT, status TEXT, requester TEXT, department TEXT,
  site TEXT, assigned_team TEXT, assigned_agent TEXT, asset_ref TEXT,
  sla_due TEXT, response_due TEXT, first_response_at TEXT, created_at TEXT,
  updated_at TEXT, resolved_at TEXT, closed_at TEXT, resolution TEXT,
  closure_category TEXT, root_cause TEXT, reopen_reason TEXT,
  escalation_level INTEGER DEFAULT 0, time_spent_min INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ticket_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, actor TEXT,
  kind TEXT, summary TEXT, detail TEXT, is_internal INTEGER DEFAULT 0,
  minutes INTEGER DEFAULT 0, created_at TEXT,
  FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE);

CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT UNIQUE, name TEXT,
  category TEXT, brand TEXT, model TEXT, serial TEXT, company TEXT, site TEXT,
  department TEXT, custodian TEXT, status TEXT, purchase_date TEXT,
  purchase_value REAL, warranty_end TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS stock_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_code TEXT UNIQUE, name TEXT,
  category TEXT, uom TEXT, quantity INTEGER, min_stock INTEGER, warehouse TEXT,
  created_at TEXT);
CREATE TABLE IF NOT EXISTS asset_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id INTEGER, actor TEXT, kind TEXT,
  summary TEXT, detail TEXT, cost REAL DEFAULT 0, created_at TEXT,
  FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE);

CREATE TABLE IF NOT EXISTS endpoints(
  id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT UNIQUE, ip TEXT, os TEXT,
  site TEXT, department TEXT, status TEXT, cpu REAL, ram REAL, disk REAL,
  uptime_h REAL, agent_ver TEXT, last_seen TEXT, asset_ref TEXT,
  api_token_hash TEXT, enrolled_at TEXT, maintenance INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS mon_alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT, severity TEXT, kind TEXT,
  message TEXT, status TEXT, ticket_ref TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS mon_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT UNIQUE, label TEXT,
  warn REAL, crit REAL, enabled INTEGER DEFAULT 1);
"""


_TICKET_MIGRATIONS = [
    ("type", "TEXT"), ("subcategory", "TEXT"), ("response_due", "TEXT"),
    ("first_response_at", "TEXT"), ("closed_at", "TEXT"), ("resolution", "TEXT"),
    ("closure_category", "TEXT"), ("root_cause", "TEXT"), ("reopen_reason", "TEXT"),
    ("escalation_level", "INTEGER DEFAULT 0"), ("time_spent_min", "INTEGER DEFAULT 0"),
]


def _migrate(conn):
    have = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)").fetchall()}
    for col, ddl in _TICKET_MIGRATIONS:
        if col not in have:
            try:
                conn.execute(f"ALTER TABLE tickets ADD COLUMN {col} {ddl}")
            except Exception:
                pass
    conn.commit()


def init_db():
    conn = sqlite3.connect(str(Config.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        _seed(conn)
    finally:
        conn.close()


def next_ref(conn, table, col, prefix, width=6, year=False):
    rows = conn.execute(f"SELECT {col} AS r FROM {table} WHERE {col} LIKE ?",
                        (f"{prefix}%",)).fetchall()
    mx = 0
    for row in rows:
        try:
            mx = max(mx, int(str(row["r"]).split("-")[-1]))
        except Exception:
            pass
    n = str(mx + 1).zfill(width)
    if year:
        return f"{prefix}-{datetime.now(timezone.utc).year}-{n}"
    return f"{prefix}-{n}"


def _seed(conn):
    cur = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    fresh = cur["c"] == 0

    # --- companies & sites ---
    if conn.execute("SELECT COUNT(*) AS c FROM companies").fetchone()["c"] == 0:
        companies = [
            ("TG-AUTO", "T-Group Automotive", "تي-جروب للسيارات"),
            ("TG-TEX", "T-Group Textile", "تي-جروب للنسيج"),
            ("TG-RE", "T-Group Real Estate", "تي-جروب العقارية"),
        ]
        for code, en, ar in companies:
            conn.execute("INSERT INTO companies(code,name_en,name_ar) VALUES(?,?,?)",
                         (code, en, ar))
        sites = [
            (1, "Head Office", "المقر الرئيسي", "hq"),
            (2, "Textile Factory", "مصنع النسيج", "factory"),
            (2, "Central Warehouse", "المستودع المركزي", "warehouse"),
            (3, "Real Estate Office", "مكتب العقارات", "office"),
        ]
        for cid, en, ar, kind in sites:
            conn.execute(
                "INSERT INTO sites(company_id,name_en,name_ar,kind) VALUES(?,?,?,?)",
                (cid, en, ar, kind))

    # --- users ---
    if fresh:
        conn.execute(
            """INSERT INTO users(username,password_hash,full_name,email,role,
               department,site,lang_pref,theme_pref,is_active,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
            (Config.ADMIN_USER, generate_password_hash(Config.ADMIN_PASSWORD),
             "System Administrator", "admin@tgroup.local", "super_admin",
             "IT", "Head Office", "en", "dark", utcnow()))
        if not Config.ADMIN_PASSWORD_FROM_ENV:
            print("=" * 60)
            print("  T-CAP first-run admin password (set TCAP_ADMIN_PASSWORD to fix):")
            print(f"  username: {Config.ADMIN_USER}   password: {Config.ADMIN_PASSWORD}")
            print("=" * 60)
        if Config.SEED_DEMO:
            demo = [
                ("itadmin", "Omar Khaled", "it_admin", "IT", "Head Office"),
                ("agent", "Sara Nabil", "it_agent", "IT", "Head Office"),
                ("assets", "Youssef Adel", "asset_manager", "Facilities", "Central Warehouse"),
                ("stock", "Mona Fathy", "stock_controller", "Warehouse", "Central Warehouse"),
                ("monitor", "Hassan Ali", "monitoring_admin", "IT Security", "Head Office"),
                ("exec", "Layla Mansour", "executive", "Executive", "Head Office"),
                ("auditor", "Karim Saad", "auditor", "Internal Audit", "Head Office"),
                ("employee", "Nour Tarek", "employee", "Production", "Textile Factory"),
            ]
            for uname, name, role, dept, site in demo:
                conn.execute(
                    """INSERT INTO users(username,password_hash,full_name,email,role,
                       department,site,lang_pref,theme_pref,is_active,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
                    (uname, generate_password_hash(Config.DEMO_PASSWORD), name,
                     f"{uname}@tgroup.local", role, dept, site, "en", "dark", utcnow()))

    # --- RBAC role permissions (seed from static defaults; editable after) ---
    if conn.execute("SELECT COUNT(*) AS c FROM role_perms").fetchone()["c"] == 0:
        from app.security import ROLES as _R, PERMISSIONS as _P
        for r, ps in _R.items():
            for p in (_P if "*" in ps else ps):
                conn.execute("INSERT OR IGNORE INTO role_perms(role,perm) VALUES(?,?)", (r, p))

    # --- ITSM tickets ---
    if conn.execute("SELECT COUNT(*) AS c FROM tickets").fetchone()["c"] == 0:
        now = datetime.now(timezone.utc)
        samples = [
            ("ERP login failure at Factory 2", "Software", "Critical", "New", "Nour Tarek", "Production", "Textile Factory", "Omar Khaled", "AST-000004"),
            ("New laptop request - Finance", "Hardware", "Low", "Assigned", "Layla Mansour", "Executive", "Head Office", "Sara Nabil", None),
            ("VPN latency at Real Estate HQ", "Network", "High", "In Progress", "Karim Saad", "Internal Audit", "Real Estate Office", "Omar Khaled", None),
            ("Printer offline - Textile line A", "Hardware", "Medium", "Resolved", "Nour Tarek", "Production", "Textile Factory", "Sara Nabil", "AST-000002"),
            ("Email quota exceeded", "Software", "Low", "Closed", "Mona Fathy", "Warehouse", "Central Warehouse", "Sara Nabil", None),
            ("Server room temperature alert", "Infrastructure", "Critical", "In Progress", "Hassan Ali", "IT Security", "Head Office", "Omar Khaled", "AST-000001"),
            ("Password reset - production floor", "Access", "Medium", "Assigned", "Nour Tarek", "Production", "Textile Factory", "Sara Nabil", None),
        ]
        for i, (subj, cat, pri, status, req, dept, site, agent, asset) in enumerate(samples):
            ref = next_ref(conn, "tickets", "ref", "ITSM", year=True)
            created = now - timedelta(days=i, hours=i * 2)
            due = created + timedelta(hours={"Critical": 4, "High": 8, "Medium": 24, "Low": 72}.get(pri, 24))
            resolved = (created + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S") if status in ("Resolved", "Closed") else None
            conn.execute(
                """INSERT INTO tickets(ref,subject,description,category,priority,impact,
                   urgency,status,requester,department,site,assigned_team,assigned_agent,
                   asset_ref,sla_due,created_at,updated_at,resolved_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ref, subj, subj + ".", cat, pri, pri, pri, status, req, dept, site,
                 "Service Desk", agent, asset, due.strftime("%Y-%m-%d %H:%M:%S"),
                 created.strftime("%Y-%m-%d %H:%M:%S"), created.strftime("%Y-%m-%d %H:%M:%S"), resolved))

        # Volume filler so lists + charts feel real (deterministic spread over 14 days).
        import random as _r
        _r.seed(42)
        subs = ["Outlook not syncing", "Wi-Fi drop in warehouse", "ERP report timeout",
                "Access request - shared drive", "Monitor flickering", "Phone extension setup",
                "Antivirus update failed", "Badge reader offline", "Backup job warning",
                "Software install request", "Disk cleanup needed", "VPN certificate renewal",
                "Meeting room display fault", "SAP export error", "Label printer jam",
                "New user onboarding", "Camera offline - dock 3", "UPS self-test alert",
                "Shared mailbox request", "Slow file server"]
        cats = ["Hardware", "Software", "Network", "Access", "Infrastructure"]
        pris = ["Critical", "High", "Medium", "Medium", "Low", "Low"]
        stns = ["New", "Assigned", "In Progress", "Pending", "Resolved", "Closed"]
        reqs = ["Nour Tarek", "Mona Fathy", "Karim Saad", "Layla Mansour", "Youssef Adel"]
        ags = ["Sara Nabil", "Omar Khaled", ""]
        deps = [("Production", "Textile Factory"), ("Warehouse", "Central Warehouse"),
                ("Executive", "Head Office"), ("Internal Audit", "Real Estate Office"),
                ("IT", "Head Office")]
        for subj in subs:
            pri = _r.choice(pris); status = _r.choice(stns); dept, site = _r.choice(deps)
            created = now - timedelta(days=_r.randint(0, 13), hours=_r.randint(0, 20))
            due = created + timedelta(hours={"Critical": 4, "High": 8, "Medium": 24, "Low": 72}[pri])
            resolved = (created + timedelta(hours=_r.randint(2, 20))).strftime("%Y-%m-%d %H:%M:%S") if status in ("Resolved", "Closed") else None
            ref = next_ref(conn, "tickets", "ref", "ITSM", year=True)
            conn.execute(
                """INSERT INTO tickets(ref,subject,description,category,priority,impact,
                   urgency,status,requester,department,site,assigned_team,assigned_agent,
                   asset_ref,sla_due,created_at,updated_at,resolved_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ref, subj, subj + ".", _r.choice(cats), pri, pri, pri, status,
                 _r.choice(reqs), dept, site, "Service Desk", _r.choice(ags), None,
                 due.strftime("%Y-%m-%d %H:%M:%S"), created.strftime("%Y-%m-%d %H:%M:%S"),
                 created.strftime("%Y-%m-%d %H:%M:%S"), resolved))

        # Enrich all tickets: type/impact/urgency, response SLA, first response,
        # normalize legacy statuses, and seed a 'created' timeline event.
        from app.itsm_core import RESPONSE_MIN, IMPACTS
        _r.seed(99)
        for row in conn.execute("SELECT id, priority, status, category, created_at, resolved_at FROM tickets").fetchall():
            c = datetime.strptime(row["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            status = "Waiting User" if row["status"] == "Pending" else row["status"]
            rmin = RESPONSE_MIN.get(row["priority"], 120)
            resp_due = (c + timedelta(minutes=rmin)).strftime("%Y-%m-%d %H:%M:%S")
            urg = row["priority"]
            imp = _r.choice(IMPACTS)
            ttype = "Service Request" if row["category"] in ("Access",) or row["priority"] == "Low" else "Incident"
            fra = None
            if status != "New":
                fra = (c + timedelta(minutes=_r.randint(4, max(6, rmin)))).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """UPDATE tickets SET status=?, type=?, impact=?, urgency=?, response_due=?,
                   first_response_at=?, closed_at=? WHERE id=?""",
                (status, ttype, imp, urg, resp_due, fra,
                 row["resolved_at"] if status == "Closed" else None, row["id"]))
            conn.execute(
                "INSERT INTO ticket_events(ticket_id,actor,kind,summary,created_at) VALUES(?,?,?,?,?)",
                (row["id"], "system", "system", "Ticket created", row["created_at"]))
            if fra:
                conn.execute(
                    "INSERT INTO ticket_events(ticket_id,actor,kind,summary,created_at) VALUES(?,?,?,?,?)",
                    (row["id"], "Service Desk", "system", "First response recorded", fra))

    # --- ASM assets & stock ---
    if conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"] == 0:
        now = datetime.now(timezone.utc)
        assets = [
            ("Dell PowerEdge R750 Server", "Server", "Dell", "R750", "SN-SRV-001", "T-Group Automotive", "Head Office", "IT", "Hassan Ali", "Assigned", 220, 40),
            ("HP LaserJet M428", "Printer", "HP", "M428", "SN-PRN-114", "T-Group Textile", "Textile Factory", "Production", "Nour Tarek", "Under Maintenance", 5, -20),
            ("Cisco Catalyst 9200", "Network", "Cisco", "C9200", "SN-NET-045", "T-Group Automotive", "Head Office", "IT", "Omar Khaled", "Assigned", 60, 400),
            ("Lenovo ThinkPad X1", "Laptop", "Lenovo", "X1C-G11", "SN-LAP-201", "T-Group Real Estate", "Real Estate Office", "Executive", "Layla Mansour", "Assigned", 30, 200),
            ("APC Smart-UPS 3000", "Power", "APC", "SMT3000", "SN-UPS-009", "T-Group Textile", "Central Warehouse", "Warehouse", "Mona Fathy", "In Stock", 12, 120),
        ]
        for name, cat, brand, model, serial, comp, site, dept, cust, status, value, warr_days in assets:
            aid = next_ref(conn, "assets", "asset_id", "AST")
            conn.execute(
                """INSERT INTO assets(asset_id,name,category,brand,model,serial,company,
                   site,department,custodian,status,purchase_date,purchase_value,
                   warranty_end,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, name, cat, brand, model, serial, comp, site, dept, cust, status,
                 (now - timedelta(days=400)).strftime("%Y-%m-%d"), value * 1000.0,
                 (now + timedelta(days=warr_days)).strftime("%Y-%m-%d"), utcnow()))
        _r.seed(7)
        anames = [("Dell OptiPlex 7010", "Desktop", "Dell", "7010"),
                  ("HP EliteBook 840", "Laptop", "HP", "840 G9"),
                  ("Canon imageRUNNER", "Printer", "Canon", "C3226"),
                  ("Ubiquiti UDM Pro", "Network", "Ubiquiti", "UDM-Pro"),
                  ('Samsung 27" Monitor', "Desktop", "Samsung", "S27"),
                  ("Zebra ZT411 Printer", "Printer", "Zebra", "ZT411"),
                  ("iPhone 14 - Field", "Mobile", "Apple", "14"),
                  ("Dell PowerVault ME5", "Server", "Dell", "ME5"),
                  ("Aruba 6100 Switch", "Network", "Aruba", "6100")]
        for j, (nm, cat, brand, model) in enumerate(anames):
            aid = next_ref(conn, "assets", "asset_id", "AST")
            comp, site = _r.choice([("T-Group Automotive", "Head Office"),
                                    ("T-Group Textile", "Textile Factory"),
                                    ("T-Group Real Estate", "Real Estate Office"),
                                    ("T-Group Textile", "Central Warehouse")])
            status = _r.choice(["Assigned", "Assigned", "In Stock", "Under Maintenance"])
            warr = _r.choice([-30, 20, 60, 120, 300, 540])
            conn.execute(
                """INSERT INTO assets(asset_id,name,category,brand,model,serial,company,
                   site,department,custodian,status,purchase_date,purchase_value,
                   warranty_end,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, nm, cat, brand, model, f"SN-{aid}", comp, site, "Operations",
                 _r.choice(["Omar Khaled", "Sara Nabil", "Mona Fathy", ""]), status,
                 (now - timedelta(days=_r.randint(90, 900))).strftime("%Y-%m-%d"),
                 float(_r.randint(4, 90) * 1000), (now + timedelta(days=warr)).strftime("%Y-%m-%d"), utcnow()))
        for row in conn.execute("SELECT id, custodian, created_at FROM assets").fetchall():
            conn.execute(
                "INSERT INTO asset_events(asset_id,actor,kind,summary,created_at) VALUES(?,?,?,?,?)",
                (row["id"], "system", "system", "Asset registered", row["created_at"]))
            if row["custodian"]:
                conn.execute(
                    "INSERT INTO asset_events(asset_id,actor,kind,summary,detail,created_at) VALUES(?,?,?,?,?,?)",
                    (row["id"], "system", "custody_assign", "Assigned to custodian", row["custodian"], row["created_at"]))
        stock = [
            ("SP-TONER-58A", "HP 58A Toner", "Consumable", "pcs", 3, 5, "Central Warehouse"),
            ("SP-RJ45", "RJ45 Connectors", "Network", "box", 40, 10, "Central Warehouse"),
            ("SP-SSD-1TB", "1TB NVMe SSD", "Hardware", "pcs", 8, 4, "Central Warehouse"),
            ("SP-UPS-BAT", "UPS Battery Pack", "Power", "pcs", 1, 3, "Central Warehouse"),
        ]
        for code, name, cat, uom, qty, mins, wh in stock:
            conn.execute(
                """INSERT INTO stock_items(item_code,name,category,uom,quantity,
                   min_stock,warehouse,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (code, name, cat, uom, qty, mins, wh, utcnow()))

    # --- Monitoring endpoints & alerts ---
    if conn.execute("SELECT COUNT(*) AS c FROM endpoints").fetchone()["c"] == 0:
        now = datetime.now(timezone.utc)
        eps = [
            ("HQ-SRV-01", "10.0.0.10", "Windows Server 2022", "Head Office", "IT", "online", 78, 64, 55, 720, "AST-000001"),
            ("HQ-DC-01", "10.0.0.11", "Windows Server 2022", "Head Office", "IT", "online", 22, 40, 33, 1440, None),
            ("FAC-PRN-01", "10.2.0.30", "Windows 11", "Textile Factory", "Production", "warning", 12, 30, 88, 96, "AST-000002"),
            ("WH-POS-02", "10.3.0.5", "Windows 10", "Central Warehouse", "Warehouse", "online", 34, 55, 61, 240, None),
            ("RE-LAP-07", "10.4.0.21", "Windows 11", "Real Estate Office", "Executive", "offline", 0, 0, 0, 0, "AST-000004"),
        ]
        for host, ip, os_, site, dept, status, cpu, ram, disk, up, asset in eps:
            seen = (now - timedelta(minutes=2)) if status != "offline" else (now - timedelta(hours=5))
            conn.execute(
                """INSERT INTO endpoints(hostname,ip,os,site,department,status,cpu,ram,
                   disk,uptime_h,agent_ver,last_seen,asset_ref)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (host, ip, os_, site, dept, status, cpu, ram, disk, up, "1.4.0",
                 seen.strftime("%Y-%m-%d %H:%M:%S"), asset))
        _r.seed(11)
        more = [("HQ-WS-{:02d}", "Head Office", "IT"), ("FAC-WS-{:02d}", "Textile Factory", "Production"),
                ("WH-WS-{:02d}", "Central Warehouse", "Warehouse"), ("RE-WS-{:02d}", "Real Estate Office", "Executive")]
        for j in range(7):
            tpl, site, dept = _r.choice(more)
            host = tpl.format(_r.randint(10, 99))
            st = _r.choice(["online", "online", "online", "warning", "offline"])
            cpu = 0 if st == "offline" else _r.randint(8, 92)
            ram = 0 if st == "offline" else _r.randint(20, 88)
            disk = 0 if st == "offline" else _r.randint(30, 95)
            seen = (now - timedelta(minutes=_r.randint(1, 8))) if st != "offline" else (now - timedelta(hours=_r.randint(5, 40)))
            try:
                conn.execute(
                    """INSERT INTO endpoints(hostname,ip,os,site,department,status,cpu,ram,
                       disk,uptime_h,agent_ver,last_seen,asset_ref)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (host, f"10.{j}.0.{_r.randint(2, 250)}", _r.choice(["Windows 11", "Windows 10", "Windows Server 2022"]),
                     site, dept, st, cpu, ram, disk, 0 if st == "offline" else _r.randint(24, 2000),
                     "1.4.0", seen.strftime("%Y-%m-%d %H:%M:%S"), None))
            except Exception:
                pass
        alerts = [
            ("HQ-SRV-01", "critical", "temperature", "Server room temperature high (34C)", "open", "ITSM-{}-000006".format(now.year)),
            ("FAC-PRN-01", "warning", "disk", "Disk usage above 85%", "open", None),
            ("RE-LAP-07", "critical", "offline", "Endpoint offline > 4h", "open", None),
            ("HQ-SRV-01", "warning", "cpu", "CPU sustained above 75%", "acknowledged", None),
        ]
        for host, sev, kind, msg, status, tref in alerts:
            conn.execute(
                """INSERT INTO mon_alerts(endpoint,severity,kind,message,status,
                   ticket_ref,created_at) VALUES(?,?,?,?,?,?,?)""",
                (host, sev, kind, msg, status, tref, utcnow()))

    # --- monitoring alert rules ---
    if conn.execute("SELECT COUNT(*) AS c FROM mon_rules").fetchone()["c"] == 0:
        for metric, label, w, c in [("cpu", "CPU %", 75, 90), ("ram", "RAM %", 80, 90),
                                    ("disk", "Disk %", 85, 95)]:
            conn.execute("INSERT INTO mon_rules(metric,label,warn,crit,enabled) VALUES(?,?,?,?,1)",
                         (metric, label, w, c))

    # --- notifications ---
    if conn.execute("SELECT COUNT(*) AS c FROM notifications").fetchone()["c"] == 0:
        for sev, mod, title, msg, link in [
            ("critical", "monitoring", "Server room temperature high", "HQ-SRV-01 reported 34C", "/monitoring"),
            ("warning", "asm", "Stock below minimum", "HP 58A Toner is below reorder level", "/asm/stock"),
            ("warning", "itsm", "SLA at risk", "ITSM ticket approaching resolution due", "/itsm"),
            ("info", "asm", "Warranty expiring", "HP LaserJet M428 warranty expiring soon", "/asm"),
        ]:
            conn.execute(
                """INSERT INTO notifications(severity,module,title,message,link,is_read,created_at)
                   VALUES(?,?,?,?,?,0,?)""", (sev, mod, title, msg, link, utcnow()))

    conn.commit()


def log_audit(username, action, detail="", ip=""):
    db = get_db()
    db.execute(
        "INSERT INTO audit_logs(username,action,detail,ip,created_at) VALUES(?,?,?,?,?)",
        (username, action, detail, ip, utcnow()))
    db.commit()
