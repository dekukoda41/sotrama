"""Shared scheduler helpers for role-aware Fleet alert assignment."""

import frappe


def _log_administrator_fallback(role_name, doctype, docname, reason):
    """Log Administrator fallback so misrouted scheduler alerts are visible.

    Logging is best-effort: it must never break the scheduler's fallback to
    Administrator. Call sites: sotrama/tp/scheduler/drivers.py (Fleet Manager /
    HR Manager on Driver), sotrama/tp/scheduler/maintenance.py (Fleet Manager on
    Maintenance Schedule), sotrama/tp/scheduler/documents.py (Fleet Manager on
    Vehicle). Writes: Error Log doctype via frappe.log_error.
    """
    try:
        frappe.log_error(
            message=(
                f"Scheduler role '{role_name}' for {doctype} {docname!r} "
                f"fell back to Administrator: {reason}"
            ),
            title="SOTRAMA Administrator Fallback",
        )
    except Exception:  # noqa: BLE001, S110 — logging must never break the scheduler fallback
        # Logging must never prevent a scheduler alert from being assigned.
        pass


def _user_for_role(
    role_name, doctype, docname, *, role_users_cache=None, known_existing=False
):
    """Return a role user who can read this exact company-scoped document."""
    if not docname or (not known_existing and not frappe.db.exists(doctype, docname)):
        _log_administrator_fallback(
            role_name, doctype, docname, "document missing or not known to exist"
        )
        return "Administrator"
    role_users_cache = role_users_cache if role_users_cache is not None else {}
    if role_name not in role_users_cache:
        role_users = frappe.get_all(
            "Has Role",
            filters={"role": role_name, "parenttype": "User"},
            pluck="parent",
            order_by="parent asc",
            limit_page_length=0,
        )
        role_users_cache[role_name] = (
            frappe.get_all(
                "User",
                filters={"name": ["in", role_users], "enabled": 1},
                pluck="name",
                order_by="name asc",
                limit_page_length=0,
            )
            if role_users
            else []
        )

    for user in role_users_cache[role_name]:
        if user == "Guest":
            continue
        try:
            if frappe.has_permission(doctype, "read", doc=docname, user=user):
                return user
        except frappe.DoesNotExistError:
            # The record may have been deleted after the scheduler batch read.
            _log_administrator_fallback(
                role_name, doctype, docname, "record deleted during batch read"
            )
            return "Administrator"
    _log_administrator_fallback(
        role_name, doctype, docname, "no enabled role user with read permission"
    )
    return "Administrator"
