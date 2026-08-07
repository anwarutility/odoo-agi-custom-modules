# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

{
    "name": "Purchase Request Auto RFQ",
    "version": "16.0.1.0.0",
    "summary": "Auto-generate draft RFQs from approved Purchase Requests "
    "with BOM breakdown",
    "category": "Purchase Management",
    "author": "PT Aston Graphindo Indonesia",
    "website": "https://www.astongraphindo.com",
    "depends": ["purchase_request", "mrp", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/bom_bootstrap_view.xml",
        "views/mrp_bom_view.xml",
        "views/purchase_request_view.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
