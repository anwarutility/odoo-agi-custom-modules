# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import re

from odoo import _, models

_MX_PREFIX = "MX-"

_BN_PREFIX_RE = re.compile(r"(?:bn[\-_])(.+)", re.IGNORECASE)


class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    def _resolve_rfq_product(self):
        """Resolve the effective product used for RFQ generation.

        BN-*/BN_* bonus codes (case-insensitive, hyphen/underscore tolerant)
        are redirected to their purchasing product, i.e. the product whose
        default_code is the remainder of the bonus code.

        Returns (product, warning): the effective product and an optional
        warning set when the line must be skipped (bonus product without a
        purchasable counterpart). No fallback to the BN- product itself.
        """
        self.ensure_one()
        code = self.product_id.default_code or ""
        match = _BN_PREFIX_RE.match(code)
        if not match:
            return (self.product_id, False)
        remainder = match.group(1)
        product = self.env["product.product"].search(
            [("default_code", "=", remainder)], limit=1
        )
        if not product:
            template = self.env["product.template"].search(
                [("default_code", "=", remainder)], limit=1
            )
            if template:
                product = template.product_variant_id
        if not product:
            return (
                self.env["product.product"],
                _(
                    "Produk bonus %s terdeteksi tapi produk pembelian %s "
                    "tidak ditemukan, baris di-skip."
                )
                % (code, remainder),
            )
        return (product, False)

    def _is_breakdown_product(self, product=None):
        """MX- finished goods need a BOM breakdown."""
        self.ensure_one()
        product = product or self.product_id
        return (product.default_code or "").startswith(_MX_PREFIX)

    def _get_breakdown_bom(self, product=None):
        """Active normal BOM for the product, using the standard Odoo
        lookup (handles multiple active BOMs via sequence)."""
        self.ensure_one()
        product = product or self.product_id
        found = self.env["mrp.bom"]._bom_find(
            product, company_id=self.company_id.id, bom_type="normal"
        )
        return found.get(product, self.env["mrp.bom"])

    def _get_breakdown_items(self, product=None, bom=None):
        """Break the MX- product down into its BOM components.

        Returns a list of tuples (product, qty, uom) where qty is expressed
        in the component purchase UoM:
            qty_component = pr_qty / bom.product_qty * bom_line.product_qty
        """
        self.ensure_one()
        product = product or self.product_id
        bom = bom or self._get_breakdown_bom(product)
        if not bom:
            return []
        qty_fg = self.product_uom_id._compute_quantity(
            self.product_qty, bom.product_uom_id
        )
        bom_factor = qty_fg / bom.product_qty
        items = []
        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id
            po_uom = component.uom_po_id or component.uom_id
            qty = bom_line.product_uom_id._compute_quantity(
                bom_factor * bom_line.product_qty, po_uom
            )
            items.append((component, qty, po_uom))
        return items

    def _get_supplier(self, product=None):
        """Default vendor for a product (company aware) together with its
        minimum order quantity. Mirrors the OCA purchase request logic."""
        self.ensure_one()
        product = product or self.product_id
        sellers = product.seller_ids.filtered(
            lambda s: not s.company_id or s.company_id == self.company_id
        )
        if not sellers:
            sellers = product.seller_ids
        seller = sellers.sorted(key=lambda s: (s.sequence, s.min_qty))[:1]
        return (seller.partner_id, seller.min_qty) if seller else (
            self.env["res.partner"],
            0.0,
        )
