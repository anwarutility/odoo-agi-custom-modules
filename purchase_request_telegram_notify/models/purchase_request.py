# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging

try:
    import requests
except ImportError:
    requests = None

from odoo import _, api, models

_logger = logging.getLogger(__name__)

TOP_FALLBACK_LOGINS = ["antonwijaya", "anwarwijaya", "danarsusilo"]


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    def write(self, vals):
        prev_state = {r.id: r.state for r in self}
        res = super(PurchaseRequest, self).write(vals)
        new_state = vals.get("state")
        if new_state:
            for rec in self:
                old = prev_state.get(rec.id)
                if old != new_state:
                    if new_state == "to_approve":
                        rec._notify_telegram_trigger_a()
                    elif new_state in ("approved", "rejected"):
                        rec._notify_telegram_trigger_b(new_state)
        return res

    def _notify_telegram_trigger_a(self):
        self.ensure_one()
        rec = self.sudo()
        recipients = rec._resolve_approver_recipients()
        if recipients:
            rec._send_telegram_to_recipients(
                recipients,
                rec._build_message_trigger_a(),
            )

    def _notify_telegram_trigger_b(self, new_state):
        self.ensure_one()
        rec = self.sudo()
        requester = rec.requested_by
        if not requester:
            return
        if not requester.telegram_chat_id:
            rec._log_skip_no_chat_id(requester)
            return
        rec._send_telegram_to_recipients(
            [requester],
            rec._build_message_trigger_b(new_state),
        )

    def _resolve_approver_recipients(self):
        self.ensure_one()
        requester = self.requested_by
        employee = requester.employee_id

        if not employee:
            return self._fallback_top_managers(
                _("Requester %s has no employee record") % requester.display_name
            )

        override = self.env["purchase.request.approval.override"].search(
            [("employee_ids", "in", employee.id), ("active", "=", True)],
            limit=2,
            order="id",
        )
        if override:
            if len(override) > 1:
                _logger.warning(
                    "Requester %s matches multiple override rules (%s), "
                    "using first (id=%s)",
                    requester.display_name,
                    override.mapped("name"),
                    override[0].id,
                )
            return self._resolve_override_recipients(override[0])

        return self._resolve_manager_chain_recipients(employee)

    def _resolve_override_recipients(self, override):
        self.ensure_one()
        recipients = override.approver_user_ids
        if not recipients:
            return self._fallback_top_managers(
                _("Override '%s' has no approvers configured") % override.name
            )
        return recipients

    def _resolve_manager_chain_recipients(self, employee):
        self.ensure_one()
        parent = employee.parent_id

        if not parent:
            return self._fallback_top_managers(
                _("Employee %s has no parent_id (manager)") % employee.name
            )

        if parent == employee:
            return self._resolve_self_approve(employee)

        if not parent.user_id:
            return self._fallback_top_managers(
                _("Manager '%s' has no Odoo user account") % parent.name
            )

        return parent.user_id

    def _resolve_self_approve(self, employee):
        requester = self.requested_by
        recipients = requester
        primary = self._get_primary_approver()
        if primary and requester != primary:
            recipients |= primary
        return recipients

    def _get_primary_approver(self):
        login = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "purchase_request_telegram_notify.primary_approver_login",
                default="antonwijaya",
            )
        )
        return self.env["res.users"].search([("login", "=", login)], limit=1)

    def _fallback_top_managers(self, reason):
        self.ensure_one()
        employees = self.env["hr.employee"].search(
            [("parent_id", "!=", False)]
        )
        top = employees.filtered(lambda e: e.parent_id.id == e.id)
        managers = top.mapped("user_id")
        if not managers:
            managers = self.env["res.users"].search(
                [("login", "in", TOP_FALLBACK_LOGINS)]
            )
        try:
            self.message_post(
                body=_("%s. Notification broadcast to top-level managers.")
                % reason
            )
        except ValueError:
            pass
        return managers

    def _send_telegram_to_recipients(self, recipients, message):
        token = self._get_bot_token()
        if not token:
            _logger.info("Bot token not configured, skipping notification")
            return
        for user in recipients:
            if not user.telegram_chat_id:
                self._log_skip_no_chat_id(user)
                continue
            self._send_telegram(user.telegram_chat_id, message, token)

    @api.model
    def _escape_html(self, text):
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _build_message_trigger_a(self):
        self.ensure_one()
        line_count = len(self.line_ids)
        total_qty = sum(self.line_ids.mapped("product_qty"))
        return _(
            "<b>PR Needs Approval</b>\n"
            "PR: %(name)s\n"
            "Requester: %(requester)s\n"
            "Lines: %(lines)s items | Total Qty: %(qty).2f\n"
            "Date: %(date)s"
        ) % {
            "name": self._escape_html(self.name),
            "requester": self._escape_html(self.requested_by.display_name),
            "lines": line_count,
            "qty": total_qty,
            "date": self.date_start or "",
        }

    def _build_message_trigger_b(self, new_state):
        self.ensure_one()
        state_label = dict(self._fields["state"].selection).get(new_state, new_state)
        approver = self.write_uid
        return _(
            "<b>PR %(state)s</b>\n"
            "PR: %(name)s\n"
            "Status: %(state_label)s\n"
            "By: %(approver)s\n"
            "Date: %(date)s"
        ) % {
            "name": self._escape_html(self.name),
            "state": new_state,
            "state_label": state_label,
            "approver": self._escape_html(approver.display_name if approver else ""),
            "date": self.write_date or "",
        }

    def _send_telegram(self, chat_id, message, token):
        if requests is None:
            _logger.warning("requests library not available, cannot send Telegram")
            return
        try:
            url = "https://api.telegram.org/bot%s/sendMessage" % token
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.status_code != 200:
                _logger.warning(
                    "Telegram API returned %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                self.message_post(
                    body=_("Telegram notification failed: API error %s")
                    % resp.status_code
                )
        except Exception as e:
            _logger.warning("Telegram send failed: %s", e)
            self.message_post(
                body=_("Telegram notification failed: %s") % e
            )

    def _get_bot_token(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("purchase_request_telegram_notify.bot_token", default="")
        )

    def _log_skip_no_chat_id(self, user):
        self.message_post(
            body=_(
                "User %s has no Telegram Chat ID registered, "
                "notification not sent."
            )
            % user.display_name
        )
