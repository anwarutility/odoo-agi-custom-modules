# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PurchaseRequestApprovalOverride(models.Model):
    _name = "purchase.request.approval.override"
    _description = "PR Approval Override Rule"
    _order = "id"

    name = fields.Char(required=True, translate=False)
    employee_ids = fields.Many2many(
        comodel_name="hr.employee",
        relation="pr_approval_override_employee_rel",
        column1="override_id",
        column2="employee_id",
        string="Requesters",
        help="Staff whose purchase requests will follow this override rule.",
    )
    approver_user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="pr_approval_override_user_rel",
        column1="override_id",
        column2="user_id",
        string="Approvers",
        help="Users who will receive Telegram notification when one "
        "of the requesters above creates a PR.",
    )
    active = fields.Boolean(default=True)


