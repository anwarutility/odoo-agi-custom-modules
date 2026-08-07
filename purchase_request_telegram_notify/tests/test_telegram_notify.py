# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTelegramNotify(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking = cls.env.ref("stock.picking_type_in")
        cls.uom = cls.env.ref("uom.product_uom_unit")
        cls.product = cls.env["product.product"].create(
            {"name": "Test Product", "type": "product"}
        )

        cls.user_top1 = cls.env["res.users"].create(
            {"name": "Top 1", "login": "top1", "password": "top1"}
        )
        cls.user_top2 = cls.env["res.users"].create(
            {"name": "Top 2", "login": "top2", "password": "top2"}
        )
        cls.user_mgr = cls.env["res.users"].create(
            {
                "name": "Manager",
                "login": "mgr",
                "password": "mgr",
                "telegram_chat_id": "123456",
            }
        )
        cls.user_staff = cls.env["res.users"].create(
            {"name": "Staff", "login": "staff", "password": "staff"}
        )
        cls.user_noemp = cls.env["res.users"].create(
            {"name": "No Employee", "login": "noemp", "password": "noemp"}
        )

        cls.emp_top1 = cls.env["hr.employee"].create(
            {"name": "Top 1 Employee", "user_id": cls.user_top1.id}
        )
        cls.emp_top1.parent_id = cls.emp_top1.id

        cls.emp_top2 = cls.env["hr.employee"].create(
            {"name": "Top 2 Employee", "user_id": cls.user_top2.id}
        )
        cls.emp_top2.parent_id = cls.emp_top2.id

        cls.emp_mgr = cls.env["hr.employee"].create(
            {"name": "Manager Employee", "user_id": cls.user_mgr.id}
        )
        cls.emp_mgr.parent_id = cls.emp_top1.id

        cls.emp_staff = cls.env["hr.employee"].create(
            {
                "name": "Staff Employee",
                "user_id": cls.user_staff.id,
                "parent_id": cls.emp_mgr.id,
            }
        )

        cls.env["ir.config_parameter"].sudo().set_param(
            "purchase_request_telegram_notify.primary_approver_login",
            "top1",
        )

    def _create_pr(self, user, state="draft"):
        return self.env["purchase.request"].create(
            {
                "requested_by": user.id,
                "picking_type_id": self.picking.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_qty": 1,
                            "product_uom_id": self.uom.id,
                        },
                    )
                ],
                "state": state,
            }
        )

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_01_manager_chain_direct(self, mock_post):
        """Staff PR -> notify direct manager"""
        mock_post.return_value.status_code = 200
        pr = self._create_pr(self.user_staff)
        recips = pr._resolve_approver_recipients()
        self.assertIn(self.user_mgr, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_02_self_approve_no_cc(self, mock_post):
        """Top-1 creates PR -> notify self only (no cc)"""
        mock_post.return_value.status_code = 200
        pr = self._create_pr(self.user_top1)
        recips = pr._resolve_approver_recipients()
        self.assertEqual(len(recips), 1)
        self.assertIn(self.user_top1, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_03_self_approve_with_cc(self, mock_post):
        """Top-2 (not Anton) creates PR -> notify self + cc Top-1"""
        mock_post.return_value.status_code = 200
        pr = self._create_pr(self.user_top2)
        recips = pr._resolve_approver_recipients()
        self.assertEqual(len(recips), 2)
        self.assertIn(self.user_top2, recips)
        self.assertIn(self.user_top1, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_04_no_employee_fallback(self, mock_post):
        """User without employee -> fallback to all self-referencing managers"""
        mock_post.return_value.status_code = 200
        pr = self._create_pr(self.user_noemp)
        recips = pr._resolve_approver_recipients()
        self.assertIn(self.user_top1, recips)
        self.assertIn(self.user_top2, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_05_override_rule_takes_priority(self, mock_post):
        """Override rule matches -> use override, skip manager chain"""
        mock_post.return_value.status_code = 200
        override = self.env["purchase.request.approval.override"].create(
            {
                "name": "Test Override",
                "employee_ids": [(4, self.emp_staff.id)],
                "approver_user_ids": [(4, self.user_top2.id)],
            }
        )
        pr = self._create_pr(self.user_staff)
        recips = pr._resolve_approver_recipients()
        self.assertIn(self.user_top2, recips)
        self.assertNotIn(self.user_mgr, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_06_skip_no_chat_id(self, mock_post):
        """Approver without telegram_chat_id -> skipped, no exception"""
        mock_post.return_value.status_code = 200
        self.user_mgr.telegram_chat_id = False
        pr = self._create_pr(self.user_staff)
        mock_post.reset_mock()
        pr._notify_telegram_trigger_a()
        mock_post.assert_not_called()

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_07_telegram_api_failure_not_blocking(self, mock_post):
        """Telegram API fails -> no exception, PR operation continues"""
        mock_post.side_effect = Exception("Network error")
        self.user_mgr.telegram_chat_id = "123456"
        pr = self._create_pr(self.user_staff)
        try:
            pr._notify_telegram_trigger_a()
        except Exception:
            self.fail("Telegram failure should not raise exception")

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_08_trigger_b_approved_notifies_requester(self, mock_post):
        """PR approved -> notify requester"""
        mock_post.return_value.status_code = 200
        self.user_staff.telegram_chat_id = "654321"
        pr = self._create_pr(self.user_staff, state="to_approve")
        pr.write({"state": "approved"})
        mock_post.assert_called()
        self.assertEqual(pr.state, "approved")

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_09_trigger_b_rejected_notifies_requester(self, mock_post):
        """PR rejected -> notify requester"""
        mock_post.return_value.status_code = 200
        self.user_staff.telegram_chat_id = "654321"
        pr = self._create_pr(self.user_staff, state="to_approve")
        pr.write({"state": "rejected"})
        mock_post.assert_called()
        self.assertEqual(pr.state, "rejected")

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_10_manager_without_user_id(self, mock_post):
        """Manager employee has no user_id -> fallback to top managers"""
        mock_post.return_value.status_code = 200
        emp_no_user = self.env["hr.employee"].create(
            {"name": "Manager No User"}
        )
        emp_no_user.parent_id = self.emp_top1.id
        self.emp_staff.parent_id = emp_no_user.id
        pr = self._create_pr(self.user_staff)
        recips = pr._resolve_approver_recipients()
        self.assertIn(self.user_top1, recips)
        self.assertIn(self.user_top2, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_11_multiple_overrides_uses_first(self, mock_post):
        """Staff matches 2 overrides -> first by id wins"""
        mock_post.return_value.status_code = 200
        self.env["purchase.request.approval.override"].create(
            {
                "name": "Override A",
                "employee_ids": [(4, self.emp_staff.id)],
                "approver_user_ids": [(4, self.user_top1.id)],
            }
        )
        self.env["purchase.request.approval.override"].create(
            {
                "name": "Override B",
                "employee_ids": [(4, self.emp_staff.id)],
                "approver_user_ids": [(4, self.user_top2.id)],
            }
        )
        pr = self._create_pr(self.user_staff)
        recips = pr._resolve_approver_recipients()
        self.assertIn(self.user_top1, recips)
        self.assertNotIn(self.user_top2, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_12_inactive_override_ignored(self, mock_post):
        """Inactive override -> fall through to manager chain"""
        mock_post.return_value.status_code = 200
        self.env["purchase.request.approval.override"].create(
            {
                "name": "Inactive Override",
                "employee_ids": [(4, self.emp_staff.id)],
                "approver_user_ids": [(4, self.user_top2.id)],
                "active": False,
            }
        )
        pr = self._create_pr(self.user_staff)
        recips = pr._resolve_approver_recipients()
        self.assertIn(self.user_mgr, recips)

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_13_no_bot_token_no_send(self, mock_post):
        """No bot token configured -> skip silently"""
        self.env["ir.config_parameter"].sudo().set_param(
            "purchase_request_telegram_notify.bot_token", ""
        )
        self.user_mgr.telegram_chat_id = "123456"
        pr = self._create_pr(self.user_staff)
        mock_post.reset_mock()
        pr._notify_telegram_trigger_a()
        mock_post.assert_not_called()

    @patch(
        "odoo.addons.purchase_request_telegram_notify"
        ".models.purchase_request.requests.post"
    )
    def test_14_non_admin_user_can_trigger_notification(self, mock_post):
        """Whole notification chain works: trigger A via manager chain"""
        mock_post.return_value.status_code = 200
        self.user_mgr.telegram_chat_id = "123456"
        self.user_staff.telegram_chat_id = "654321"
        pr = self._create_pr(self.user_staff)
        pr._notify_telegram_trigger_a()
        mock_post.assert_called()
