"""Real Frappe integration tests for Sotrama security boundaries.

These tests use real users, roles, Company User Permissions, documents and
database state. They do not mock frappe.has_permission, frappe.db.get_value or
other authorization boundaries. They run inside the CI frappe-integration job
against a real Bench with Frappe 16.61.0, ERPNext 16.61.0 and HRMS 16.60.0.
"""

import unittest

import frappe

from sotrama.tests.helpers import _delete_test_record, _get_test_company
from sotrama.tp.settings import validate_company_access


class TestValidateCompanyAccessIntegration(unittest.TestCase):
    """validate_company_access must enforce real Company User Permissions."""

    def setUp(self):
        self.company = _get_test_company()
        self.admin_user = "Administrator"
        self.test_user = f"fleet-int-{__import__('uuid').uuid4().hex[:8]}@example.invalid"
        self.created_docs = []

    def tearDown(self):
        frappe.set_user(self.admin_user)
        for doctype, name in reversed(self.created_docs):
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, ignore_on_trash=True)
        self.created_docs = []

    def _create_fleet_user(self):
        user = frappe.new_doc("User")
        user.email = self.test_user
        user.first_name = "Fleet Integration"
        user.enabled = 1
        user.user_type = "System User"
        user.insert(ignore_permissions=True)
        self.created_docs.append(("User", self.test_user))

        role = frappe.new_doc("Has Role")
        role.parent = self.test_user
        role.parenttype = "User"
        role.parentfield = "roles"
        role.role = "Fleet Manager"
        role.insert(ignore_permissions=True)
        self.created_docs.append(("Has Role", role.name))

    def _grant_company_permission(self, company, applicable_for=None):
        perm = frappe.new_doc("User Permission")
        perm.user = self.test_user
        perm.allow = "Company"
        perm.for_value = company
        perm.applicable_for = applicable_for or ""
        perm.insert(ignore_permissions=True)
        self.created_docs.append(("User Permission", perm.name))

    def test_allows_company_with_user_permission(self):
        """A user with a Company User Permission may use that company."""
        self._create_fleet_user()
        self._grant_company_permission(self.company, "Vehicle")
        frappe.set_user(self.test_user)

        result = validate_company_access(self.company, "Vehicle")
        self.assertEqual(result, self.company)

    def test_rejects_non_existent_company(self):
        """A company that does not exist is rejected regardless of permissions."""
        self._create_fleet_user()
        self._grant_company_permission(self.company, "Vehicle")
        frappe.set_user(self.test_user)

        with self.assertRaises(frappe.PermissionError):
            validate_company_access("DOES-NOT-EXIST", "Vehicle")

    def test_allows_any_company_when_no_user_permissions(self):
        """Without any Company User Permission, no restriction is applied."""
        self._create_fleet_user()
        frappe.set_user(self.test_user)

        result = validate_company_access(self.company, "Vehicle")
        self.assertEqual(result, self.company)

    def test_rejects_other_company_with_applicable_for_scope(self):
        """A permission scoped to one company blocks another for the same doctype."""
        self._create_fleet_user()
        self._grant_company_permission(self.company, "Vehicle")
        frappe.set_user(self.test_user)

        with self.assertRaises(frappe.PermissionError):
            validate_company_access("OTHER-COMPANY", "Vehicle")


class TestDriverCompanyIsolationIntegration(unittest.TestCase):
    """Driver records must be scoped to their Company in real Frappe lookups."""

    def setUp(self):
        self.company = _get_test_company()
        self.admin_user = "Administrator"
        self.test_user = f"fleet-drv-{__import__('uuid').uuid4().hex[:8]}@example.invalid"
        self.driver_name = None

    def tearDown(self):
        frappe.set_user(self.admin_user)
        if self.driver_name and frappe.db.exists("Driver", self.driver_name):
            _delete_test_record("Driver", self.driver_name)

    def _create_driver(self, company, name_suffix=""):
        driver = frappe.new_doc("Driver")
        driver.driver_name = f"Integration Driver {name_suffix}"
        driver.company = company
        driver.license_number = f"LIC-{__import__('uuid').uuid4().hex[:8]}"
        driver.license_expiry = frappe.utils.add_days(frappe.utils.today(), 365)
        driver.insert(ignore_permissions=True)
        return driver.name

    def test_driver_company_field_is_required(self):
        """Every Driver must have a Company for company isolation."""
        meta = frappe.get_meta("Driver", cached=False)
        company_field = meta.get_field("company")
        self.assertTrue(company_field.reqd, "Driver.company must be mandatory")

    def test_driver_belongs_to_single_company(self):
        """A Driver record carries exactly one Company link."""
        self.driver_name = self._create_driver(self.company)
        driver = frappe.get_doc("Driver", self.driver_name)
        self.assertEqual(driver.company, self.company)


class TestCompanyUserPermissionApplicableForIntegration(unittest.TestCase):
    """applicable_for on Company User Permission must match Frappe semantics."""

    def setUp(self):
        self.company = _get_test_company()
        self.admin_user = "Administrator"
        self.test_user = f"fleet-apf-{__import__('uuid').uuid4().hex[:8]}@example.invalid"
        self.created_docs = []

    def tearDown(self):
        frappe.set_user(self.admin_user)
        for doctype, name in reversed(self.created_docs):
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, ignore_on_trash=True)
        self.created_docs = []

    def _create_driver_user(self):
        user = frappe.new_doc("User")
        user.email = self.test_user
        user.first_name = "Driver APF Integration"
        user.enabled = 1
        user.user_type = "System User"
        user.insert(ignore_permissions=True)
        self.created_docs.append(("User", self.test_user))

        role = frappe.new_doc("Has Role")
        role.parent = self.test_user
        role.parenttype = "User"
        role.parentfield = "roles"
        role.role = "Fleet Manager"
        role.insert(ignore_permissions=True)
        self.created_docs.append(("Has Role", role.name))

    def test_applicable_for_restricts_to_matching_doctype_only(self):
        """A permission with applicable_for=Driver does not unlock Vehicle scope."""
        self._create_driver_user()
        frappe.get_doc({
            "doctype": "User Permission",
            "user": self.test_user,
            "allow": "Company",
            "for_value": self.company,
            "applicable_for": "Driver",
        }).insert(ignore_permissions=True)

        frappe.set_user(self.test_user)

        # Same company, matching doctype -> allowed
        result = validate_company_access(self.company, "Driver")
        self.assertEqual(result, self.company)

        # Same company, no applicable_for -> allowed (no unrestricted perms exist)
        result = validate_company_access(self.company)
        self.assertEqual(result, self.company)

        # Different company, matching doctype -> rejected
        with self.assertRaises(frappe.PermissionError):
            validate_company_access("OTHER-COMPANY", "Driver")
