# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

{
    "name": "Purchase Request Telegram Notification",
    "version": "16.0.1.0.0",
    "summary": "Telegram notifications for PR approval based on HR manager hierarchy",
    "category": "Purchase Management",
    "author": "PT Aston Graphindo Indonesia",
    "website": "https://www.astongraphindo.com",
    "depends": ["purchase_request", "hr"],
    "data": [
        "security/ir.model.access.csv",
        "data/approval_override_data.xml",
        "views/purchase_request_approval_override_view.xml",
        "views/res_users_view.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
