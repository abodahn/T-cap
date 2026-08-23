"""Role-based access control for T-CAP.

A small static catalogue of permissions and a role->permissions map. `"*"` grants
everything (super admin). Menu visibility and route guards both consult this.
"""

DEFAULT_ROLE = "employee"

# module.action style permission keys
PERMISSIONS = {
    "view_dashboard",
    # ITSM  (itsm_view = see your own tickets; itsm_view_all = see everyone's)
    "itsm_view", "itsm_view_all", "itsm_create", "itsm_edit", "itsm_assign", "itsm_close",
    # ASM
    "asm_view", "asm_create", "asm_edit", "asm_delete",
    # Monitoring
    "mon_view", "mon_manage",
    # HR  (hr_view = own record; hr_view_all = directory; hr_manage = edit + payroll/bank)
    "hr_view", "hr_view_all", "hr_manage",
    # Platform / admin
    "reports_view", "admin_access", "manage_users", "manage_settings",
}

# NOTE: itsm_view_all = "see every ticket". Roles WITHOUT it (only itsm_view)
# see just the tickets they raised — this is what makes 'employee' own-only.
ROLES = {
    "super_admin":     {"*"},
    "it_admin":        {"view_dashboard", "itsm_view", "itsm_view_all", "itsm_create",
                        "itsm_edit", "itsm_assign", "itsm_close", "asm_view", "asm_create",
                        "asm_edit", "mon_view", "mon_manage", "reports_view",
                        "admin_access", "manage_users"},
    "it_agent":        {"view_dashboard", "itsm_view", "itsm_view_all", "itsm_create",
                        "itsm_edit", "itsm_assign", "itsm_close", "asm_view", "mon_view",
                        "reports_view"},
    "asset_manager":   {"view_dashboard", "asm_view", "asm_create", "asm_edit",
                        "asm_delete", "itsm_view", "itsm_view_all", "reports_view"},
    "stock_controller":{"view_dashboard", "asm_view", "asm_create", "asm_edit",
                        "reports_view"},
    "monitoring_admin":{"view_dashboard", "mon_view", "mon_manage", "itsm_view",
                        "itsm_view_all", "reports_view"},
    "security_viewer": {"view_dashboard", "mon_view", "reports_view"},
    "dept_manager":    {"view_dashboard", "itsm_view", "itsm_view_all", "itsm_create",
                        "asm_view", "reports_view"},
    "executive":       {"view_dashboard", "itsm_view", "itsm_view_all", "asm_view",
                        "mon_view", "reports_view"},
    "auditor":         {"view_dashboard", "itsm_view", "itsm_view_all", "asm_view",
                        "mon_view", "reports_view"},
    # employee: itsm_view only (NOT itsm_view_all) => sees & works ONLY own tickets.
    "employee":        {"view_dashboard", "itsm_view", "itsm_create", "asm_view"},
    # HR manager: full HR module (directory + payroll/bank + import), plus can raise tickets.
    "hr_manager":      {"view_dashboard", "hr_view", "hr_view_all", "hr_manage",
                        "itsm_view", "itsm_create", "reports_view"},
}

# Permissions grouped by module (for the matrix UI) + human labels.
PERMISSION_GROUPS = {
    "Platform": ["view_dashboard", "reports_view", "admin_access", "manage_users", "manage_settings"],
    "ITSM": ["itsm_view", "itsm_view_all", "itsm_create", "itsm_edit", "itsm_assign", "itsm_close"],
    "Assets": ["asm_view", "asm_create", "asm_edit", "asm_delete"],
    "Monitoring": ["mon_view", "mon_manage"],
    "HR": ["hr_view", "hr_view_all", "hr_manage"],
}
PERMISSION_LABELS = {
    "view_dashboard": "Dashboard", "reports_view": "Reports", "admin_access": "Admin access",
    "manage_users": "Manage users", "manage_settings": "Manage settings",
    "itsm_view": "View own tickets", "itsm_view_all": "View all tickets",
    "itsm_create": "Create tickets", "itsm_edit": "Work tickets",
    "itsm_assign": "Assign", "itsm_close": "Resolve/Close",
    "asm_view": "View assets", "asm_create": "Create assets", "asm_edit": "Edit assets",
    "asm_delete": "Delete assets", "mon_view": "View monitoring", "mon_manage": "Manage monitoring",
    "hr_view": "View own HR record", "hr_view_all": "HR directory (all staff)",
    "hr_manage": "Manage HR (edit + payroll)",
}
# Module -> permissions that mean "full control" vs "view only" (responsibility matrix)
MODULE_PERMS = {
    "ITSM": ("itsm_edit", "itsm_view"),
    "Assets": ("asm_edit", "asm_view"),
    "Monitoring": ("mon_manage", "mon_view"),
    "HR": ("hr_manage", "hr_view_all"),
    "Reports": (None, "reports_view"),
    "Admin": ("manage_users", "admin_access"),
}

# Human labels (EN); AR labels live in the i18n dictionary under role.<key>.
ROLE_LABELS = {
    "super_admin": "Super Admin", "it_admin": "IT Admin", "it_agent": "IT Agent",
    "asset_manager": "Asset Manager", "stock_controller": "Stock Controller",
    "monitoring_admin": "Monitoring Admin", "security_viewer": "Security Viewer",
    "dept_manager": "Department Manager", "executive": "Executive",
    "auditor": "Auditor / Read-only", "employee": "Employee",
    "hr_manager": "HR Manager",
}


def role_can(role, perm):
    perms = ROLES.get(role, ROLES[DEFAULT_ROLE])
    return "*" in perms or perm in perms
