"""Notifications engine: in-app records + optional email, plus a lazy sweep that
raises SLA-breach and stock-low alerts (deduped). No scheduler required — the
sweep runs on dashboard/notifications load."""
import smtplib
from email.message import EmailMessage

from config import Config
from app.db import utcnow
from app import itsm_core as core


def send_email(to, subject, body, link=""):
    """Best-effort email. Returns True if sent. No-op (False) when SMTP unset."""
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r]
    if not Config.SMTP_HOST or not recipients:
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[{Config.ORG_NAME} · T-CAP] {subject}"
        msg["From"] = Config.SMTP_FROM
        msg["To"] = ", ".join(recipients)
        url = (Config.PUBLIC_URL + link) if (Config.PUBLIC_URL and link) else ""
        msg.set_content(f"{subject}\n\n{body}\n\n{url}".strip())
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=8) as s:
            if Config.SMTP_TLS:
                s.starttls()
            if Config.SMTP_USER:
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as exc:
        print(f"[notify] email failed: {exc}")
        return False


def notify(db, severity, module, title, message, link="", target_user=None,
           email_to=None, dedup=None):
    """Insert an in-app notification (deduped by `dedup` while unread) and, if an
    email address is supplied and SMTP is configured, send an email too."""
    if dedup:
        seen = db.execute(
            "SELECT 1 FROM notifications WHERE ext_key=? AND is_read=0", (dedup,)).fetchone()
        if seen:
            return False
    db.execute(
        """INSERT INTO notifications(severity,module,title,message,link,target_user,
           ext_key,is_read,created_at) VALUES(?,?,?,?,?,?,?,0,?)""",
        (severity, module, title, message, link, target_user, dedup, utcnow()))
    if email_to:
        send_email(email_to, title, message, link)
    return True


def run_checks(db):
    """Sweep for SLA breaches and low stock, raising deduped notifications.
    Idempotent while the underlying condition persists (ext_key dedup)."""
    created = 0
    # SLA breaches on open tickets
    for tk in db.execute(
            "SELECT * FROM tickets WHERE status NOT IN ('Resolved','Closed','Cancelled')").fetchall():
        sla = core.compute_sla(tk)
        if sla["breached"]:
            email = None
            if tk["assigned_agent"]:
                row = db.execute("SELECT email FROM users WHERE full_name=?", (tk["assigned_agent"],)).fetchone()
                email = row["email"] if row else None
            email = email or (Config.ALERT_EMAILS or None)
            if notify(db, "critical", "itsm", f"SLA breached · {tk['ref']}",
                      f"{tk['subject']} ({tk['priority']}) has breached its resolution SLA.",
                      link=f"/itsm/{tk['ref']}", target_user=None, email_to=email,
                      dedup=f"sla:{tk['ref']}"):
                created += 1
    # Low stock
    for it in db.execute("SELECT * FROM stock_items WHERE quantity <= min_stock").fetchall():
        out = (it["quantity"] or 0) <= 0
        if notify(db, "critical" if out else "warning", "asm",
                  ("Out of stock" if out else "Low stock") + f" · {it['name']}",
                  f"{it['name']} ({it['item_code']}): qty {it['quantity']}, min {it['min_stock']}.",
                  link="/asm/stock", email_to=(Config.ALERT_EMAILS or None),
                  dedup=f"stock:{it['item_code']}"):
            created += 1
    if created:
        db.commit()
    return created


def notify_assignment(db, ticket, agent_full_name):
    """Notify an agent they were assigned a ticket (in-app + email)."""
    row = db.execute("SELECT username, email FROM users WHERE full_name=?", (agent_full_name,)).fetchone()
    if not row:
        return
    notify(db, "info", "itsm", f"Assigned to you · {ticket['ref']}",
           f"{ticket['subject']} ({ticket['priority']}) was assigned to you.",
           link=f"/itsm/{ticket['ref']}", target_user=row["username"],
           email_to=row["email"], dedup=None)
