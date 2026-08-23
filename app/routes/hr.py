"""HR module — employee directory + Excel importer.

Phase 1: a searchable/paginated staff directory and an in-app importer that
loads the HR master spreadsheet (Arabic or English headers) into the DB.
Confidential fields (salary, insurance wage, bank details, advances) are only
rendered to users with hr_manage. Employee data is never seeded into git — it
enters the database only through this importer at runtime.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   abort, flash)

from app.db import get_db, utcnow, log_audit
from app.auth import permission_required, current_user, user_can

bp = Blueprint("hr", __name__, url_prefix="/hr")

# Spreadsheet header (Arabic master or English) -> employees column.
HEADER_MAP = {
    "الكود": "employee_no", "code": "employee_no", "employee_no": "employee_no", "emp_no": "employee_no",
    "الاسم بالعربية": "name_ar", "name_ar": "name_ar", "arabic name": "name_ar",
    "الاسم بالإنجليزية": "name_en", "name_en": "name_en", "english name": "name_en", "name": "name_en",
    "الإدارة": "department", "department": "department", "dept": "department",
    "القسم": "section", "section": "section",
    "المسمى الوظيفي": "job_title", "job_title": "job_title", "title": "job_title",
    "الموقع": "location", "location": "location",
    "المرتب الأساسي": "basic_salary", "basic_salary": "basic_salary", "basic": "basic_salary",
    "الأجر التأميني": "insurance_wage", "insurance_wage": "insurance_wage",
    "كود البنك": "bank_code", "bank_code": "bank_code",
    "اسم البنك": "bank_name", "bank_name": "bank_name", "bank": "bank_name",
    "الحساب البنكي": "bank_account", "bank_account": "bank_account", "account": "bank_account",
    "يمكن الدفع؟": "payable", "payable": "payable",
    "رصيد السلفة": "advance_balance", "advance_balance": "advance_balance",
    "قسط السلفة": "advance_installment", "advance_installment": "advance_installment",
    "الحالة / المشاكل": "notes", "الحالة": "notes", "notes": "notes", "status": "notes",
}
_NUMERIC = {"basic_salary", "insurance_wage", "advance_balance", "advance_installment"}
# Columns hidden from the list and gated behind hr_manage on the detail view.
CONFIDENTIAL = ("basic_salary", "insurance_wage", "bank_code", "bank_name",
                "bank_account", "advance_balance", "advance_installment")
PAGE = 50


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _cell(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def import_workbook(db, ws):
    """Upsert employees from an openpyxl worksheet keyed by employee_no.
    Returns (inserted, updated, skipped)."""
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None) or []
    # Map each spreadsheet column index -> our field name.
    idx = {}
    for i, h in enumerate(header):
        if h is None:
            continue
        field = HEADER_MAP.get(str(h).strip()) or HEADER_MAP.get(str(h).strip().lower())
        if field:
            idx[i] = field
    if "employee_no" not in idx.values():
        raise ValueError("no_employee_code_column")

    ins = upd = skip = 0
    now = utcnow()
    for row in rows:
        data = {}
        for i, field in idx.items():
            val = row[i] if i < len(row) else None
            data[field] = _num(val) if field in _NUMERIC else _cell(val)
        empno = data.get("employee_no")
        if not empno:
            skip += 1
            continue
        cols = [c for c in data if c != "employee_no"]
        existing = db.execute("SELECT id FROM employees WHERE employee_no=?", (empno,)).fetchone()
        if existing:
            if cols:
                sets = ", ".join(f"{c}=?" for c in cols) + ", updated_at=?"
                db.execute(f"UPDATE employees SET {sets} WHERE employee_no=?",
                           [data[c] for c in cols] + [now, empno])
            upd += 1
        else:
            allcols = ["employee_no"] + cols + ["created_at", "updated_at"]
            ph = ",".join(["?"] * len(allcols))
            db.execute(f"INSERT INTO employees({','.join(allcols)}) VALUES({ph})",
                       [empno] + [data[c] for c in cols] + [now, now])
            ins += 1
    return ins, upd, skip


@bp.route("/")
@permission_required("hr_view_all")
def index():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    dept = request.args.get("dept") or ""
    where, p = "1=1", []
    if q:
        where += " AND (name_en LIKE ? OR name_ar LIKE ? OR employee_no LIKE ?)"; p += [f"%{q}%"] * 3
    if dept:
        where += " AND department=?"; p.append(dept)
    total = db.execute("SELECT COUNT(*) FROM employees WHERE " + where, p).fetchone()[0]
    try:
        page = max(1, int(request.args.get("page") or 1))
    except ValueError:
        page = 1
    pages = max(1, (total + PAGE - 1) // PAGE)
    rows = db.execute("SELECT * FROM employees WHERE " + where +
                      " ORDER BY name_en, employee_no LIMIT ? OFFSET ?",
                      p + [PAGE, (page - 1) * PAGE]).fetchall()
    depts = [r[0] for r in db.execute("SELECT DISTINCT department FROM employees WHERE department IS NOT NULL AND department<>'' ORDER BY department").fetchall()]
    return render_template("hr/list.html", employees=rows, q=q, dept=dept, depts=depts,
                           total=total, shown=len(rows), page=page, pages=pages,
                           can_manage=user_can("hr_manage"))


@bp.route("/<employee_no>")
@permission_required("hr_view_all")
def view(employee_no):
    db = get_db()
    e = db.execute("SELECT * FROM employees WHERE employee_no=?", (employee_no,)).fetchone()
    if not e:
        abort(404)
    mgr = db.execute("SELECT name_en,employee_no FROM employees WHERE id=?", (e["manager_id"],)).fetchone() if e["manager_id"] else None
    return render_template("hr/detail.html", e=e, mgr=mgr,
                           can_manage=user_can("hr_manage"), confidential=CONFIDENTIAL)


@bp.route("/import", methods=["GET", "POST"])
@permission_required("hr_manage")
def import_data():
    db = get_db()
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith((".xlsx", ".xlsm")):
            flash("hr_import_bad_file")
            return redirect(url_for("hr.import_data"))
        try:
            import openpyxl
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            ins, upd, skip = import_workbook(db, wb.active)
            db.commit()
            log_audit(current_user()["username"], "hr_import", f"+{ins} ~{upd} skip{skip}")
            flash(f"hr_import_done:{ins}:{upd}:{skip}")
        except ValueError as ex:
            flash("hr_import_no_code" if str(ex) == "no_employee_code_column" else "hr_import_error")
        except Exception:
            flash("hr_import_error")
        return redirect(url_for("hr.index"))
    return render_template("hr/import.html")
