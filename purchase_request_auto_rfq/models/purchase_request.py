# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import _, api, fields, models
from odoo.exceptions import UserError

DEFAULT_BUYER_LOGIN = "harypurwoko"


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    rfq_count = fields.Integer(
        string="RFQ count", compute="_compute_rfq_count", readonly=True
    )

    @api.depends("line_ids.purchase_lines.order_id.state")
    def _compute_rfq_count(self):
        for rec in self:
            orders = rec.mapped("line_ids.purchase_lines.order_id").filtered(
                lambda o: o.state == "draft"
            )
            rec.rfq_count = len(orders)

    def action_view_rfq(self):
        """Smart button: draft RFQs linked to this request."""
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("purchase.purchase_rfq")
        orders = self.mapped("line_ids.purchase_lines.order_id").filtered(
            lambda o: o.state == "draft"
        )
        if len(orders) > 1:
            action["domain"] = [("id", "in", orders.ids)]
        elif orders:
            action["views"] = [
                (self.env.ref("purchase.purchase_order_form").id, "form")
            ]
            action["res_id"] = orders.id
        return action

    def write(self, vals):
        """Trigger RFQ generation when the request reaches the final
        'approved' state (single choke point: OCA's button_approved only
        writes the state, and direct writes are covered as well)."""
        to_generate = self.env["purchase.request"]
        if vals.get("state") == "approved":
            to_generate = self.filtered(lambda r: r.state != "approved")
        res = super(PurchaseRequest, self).write(vals)
        if to_generate:
            to_generate._generate_rfqs()
        return res

    def action_generate_rfq(self):
        """Manual re-trigger, used as fallback e.g. when the generated RFQs
        were deleted manually. Anti-duplication still applies."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(
                    _(
                        "RFQs can only be generated for an approved "
                        "purchase request. (%s)"
                    )
                    % rec.name
                )
        self._generate_rfqs()
        return {
            "type": "ir.actions.act_window",
            "name": _("RFQs"),
            "res_model": "purchase.order",
            "view_mode": "tree,form",
            "domain": [
                (
                    "id",
                    "in",
                    self.mapped("line_ids.purchase_lines.order_id").ids,
                )
            ],
        }

    def _get_default_buyer(self):
        """Buyer set on every generated RFQ.

        Lookup is by login (not name). Returns (user, missing) where
        missing is True when the configured buyer cannot be found, in
        which case the caller must fall back to the platform default and
        warn the user.
        """
        self.ensure_one()
        user = self.env["res.users"].search(
            [("login", "=", DEFAULT_BUYER_LOGIN)], limit=1
        )
        return (user, not bool(user))

    def _generate_rfqs(self):
        for request in self:
            request._generate_rfq()

    def _generate_rfq(self):
        self.ensure_one()
        warnings = []
        buyer, buyer_missing = self._get_default_buyer()
        if buyer_missing:
            warnings.append(
                _(
                    "User default buyer (login: %s) tidak ditemukan, "
                    "RFQ dibuat dengan buyer default"
                )
                % DEFAULT_BUYER_LOGIN
            )
        # supplier -> {"supplier", "items": {product_id: {"product", "uom",
        #             "contributions": [(pr_line, qty)]}}}
        grouped = {}
        for line in self.line_ids.filtered(lambda l: not l.cancelled):
            if not line.product_id:
                continue
            product, warning = line._resolve_rfq_product()
            if warning:
                warnings.append(warning)
                continue
            if line._is_breakdown_product(product):
                bom = line._get_breakdown_bom(product)
                if not bom:
                    warnings.append(
                        _(
                            "Produk %s belum punya BOM aktif. RFQ tidak "
                            "digenerate untuk baris ini."
                        )
                        % (product.default_code or product.name)
                    )
                    continue
                items = line._get_breakdown_items(product, bom)
            else:
                po_uom = product.uom_po_id or product.uom_id
                qty = line.product_uom_id._compute_quantity(
                    line.product_qty, po_uom
                )
                items = [(product, qty, po_uom)]

            for product, qty, uom in items:
                existing = line.purchase_lines.filtered(
                    lambda l: l.product_id.id == product.id
                    and l.order_id.state != "cancel"
                )
                if existing:
                    warnings.append(
                        _(
                            "Produk %s untuk baris %s sudah tercakup oleh "
                            "RFQ/PO %s. Tidak digenerate ulang."
                        )
                        % (
                            product.default_code or product.name,
                            line.name,
                            existing[0].order_id.name,
                        )
                    )
                    continue
                supplier, min_qty = line._get_supplier(product)
                if not supplier:
                    warnings.append(
                        _(
                            "Produk %s tidak punya vendor. RFQ tidak "
                            "digenerate untuk komponen ini."
                        )
                        % (product.default_code or product.name)
                    )
                    continue
                qty = max(qty, min_qty)
                group = grouped.setdefault(
                    supplier.id, {"supplier": supplier, "items": {}}
                )
                item = group["items"].setdefault(
                    product.id,
                    {
                        "product": product,
                        "uom": uom,
                        "contributions": [],
                    },
                )
                item["contributions"].append((line, qty))

        created_orders = self.env["purchase.order"]
        for group in grouped.values():
            po = self._create_rfq(group, buyer)
            created_orders |= po

        self._post_generation_messages(created_orders, warnings)
        return created_orders

    def _create_rfq(self, group, buyer):
        """Create one draft purchase.order (RFQ) for a vendor group and link
        every generated line back to the source purchase request lines using
        the OCA relation + allocations."""
        supplier = group["supplier"]
        vals = {
            "partner_id": supplier.id,
            "origin": self.name,
            "company_id": self.company_id.id,
            "picking_type_id": self.picking_type_id.id,
            "group_id": self.group_id.id,
            "fiscal_position_id": supplier.property_account_position_id.id
            if supplier.property_account_position_id
            else False,
        }
        if buyer:
            vals["user_id"] = buyer.id
        po = self.env["purchase.order"].create(vals)
        for product, item in group["items"].items():
            self._create_rfq_line(po, item)
        return po

    def _create_rfq_line(self, po, item):
        product = item["product"]
        uom = item["uom"]
        contributions = item["contributions"]
        total_qty = sum(qty for _line, qty in contributions)
        name = self._get_rfq_line_name(po, product)
        dates = [
            line.date_required
            for line, _qty in contributions
            if line.date_required
        ]
        if dates:
            date_planned = min(dates)
        else:
            date_planned = fields.Date.context_today(self)
        move_dest_ids = [
            (4, move.id)
            for line, _qty in contributions
            for move in line.move_dest_ids
        ]
        po_line = self.env["purchase.order.line"].create(
            {
                "order_id": po.id,
                "product_id": product.id,
                "product_uom": uom.id,
                "product_qty": total_qty,
                "price_unit": 0.0,
                "name": name,
                "date_planned": date_planned,
                "move_dest_ids": move_dest_ids,
            }
        )
        for line, qty in contributions:
            po_line.purchase_request_lines = [(4, line.id)]
            self.env["purchase.request.allocation"].create(
                {
                    "requested_product_uom_qty": qty,
                    "product_uom_id": uom.id,
                    "purchase_request_line_id": line.id,
                    "purchase_line_id": po_line.id,
                }
            )
        return po_line

    @api.model
    def _get_rfq_line_name(self, po, product):
        product_lang = product.with_context(
            lang=po.partner_id.lang or self.env.user.lang,
            partner_id=po.partner_id.id,
            company_id=po.company_id.id,
        )
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase
        return name

    def _post_generation_messages(self, orders, warnings):
        if orders:
            lines_html = "".join(
                "<li><b>%s</b>: %s</li>"
                % (order.partner_id.name, self._format_order(order))
                for order in orders
            )
            self.message_post(
                body=_(
                    "RFQ berikut digenerate otomatis untuk purchase "
                    "request ini:<ul>%s</ul>"
                )
                % lines_html
            )
        if warnings:
            self.message_post(
                body=_(
                    "<b>Perhatian:</b><ul>%s</ul>"
                )
                % "".join("<li>%s</li>" % w for w in warnings)
            )
        elif not orders:
            self.message_post(
                body=_(
                    "Tidak ada RFQ yang digenerate untuk purchase request "
                    "ini (tidak ada baris yang valid)."
                )
            )

    @api.model
    def _format_order(self, order):
        lines = "; ".join(
            "%s: %s %s" % (line.product_id.default_code or line.product_id.name,
                           line.product_qty, line.product_uom.name)
            for line in order.order_line
        )
        return "%s (%s)" % (order.name, lines)
