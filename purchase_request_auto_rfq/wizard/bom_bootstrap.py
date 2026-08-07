# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_PREFIX_MX = "MX-"


class PurchaseRequestBomBootstrap(models.TransientModel):
    _name = "purchase.request.bom.bootstrap"
    _description = "Bootstrap BOM Generator"

    line_ids = fields.One2many(
        comodel_name="purchase.request.bom.bootstrap.line",
        inverse_name="wizard_id",
        string="MX Products",
    )

    @api.model
    def _get_mx_templates_without_bom(self):
        """All MX- product templates without an active normal BOM."""
        mx_templates = self.env["product.template"].search(
            [("default_code", "=like", _PREFIX_MX + "%")]
        )
        if not mx_templates:
            return self.env["product.template"]
        existing_boms = self.env["mrp.bom"].search(
            [
                ("product_tmpl_id", "in", mx_templates.ids),
                ("active", "=", True),
                ("type", "=", "normal"),
            ]
        )
        return mx_templates - existing_boms.mapped("product_tmpl_id")

    @api.model
    def _extract_suffix(self, code):
        if not code or not code.startswith(_PREFIX_MX):
            return False
        return code[len(_PREFIX_MX):]

    @api.model
    def _find_components(self, mx_template):
        """Find COMP-*/BOX_* products matching the MX- code suffix,
        tolerant to '-' vs '_' separators."""
        suffix = self._extract_suffix(mx_template.default_code)
        if not suffix:
            return self.env["product.product"]

        candidates = []
        for prefix in ("COMP", "BOX"):
            for sep in ("-", "_"):
                candidates.append(prefix + sep + suffix)
        components = self.env["product.product"].search(
            [("default_code", "in", candidates)]
        )
        if components:
            return components

        def _normalize(code):
            return (code or "").lower().replace("-", "").replace("_", "")

        normalized_suffix = _normalize(suffix)
        pool = self.env["product.product"].search(
            [
                "|",
                "|",
                ("default_code", "like", "COMP-%"),
                ("default_code", "like", "COMP_%"),
                ("default_code", "like", "BOX_%"),
            ]
        )
        targets = (
            _normalize("COMP-" + suffix),
            _normalize("BOX_" + suffix),
        )
        return pool.filtered(
            lambda p: _normalize(p.default_code) in targets
        )

    def action_preview(self):
        """Scan MX- products without active BOM and fill the wizard lines."""
        self.ensure_one()
        templates = self._get_mx_templates_without_bom()
        lines = []
        for template in templates:
            components = self._find_components(template)
            lines.append(
                (
                    0,
                    0,
                    {
                        "product_tmpl_id": template.id,
                        "component_ids": [(6, 0, components.ids)],
                        "status": "ok" if components else "no_match",
                    },
                )
            )
        self.line_ids = [(5, 0, 0)] + lines
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
            "name": _("Bootstrap BOM Generator"),
        }

    def action_generate(self):
        """Create draft BOMs for all matched wizard lines, skipping the
        ones that already got a BOM (either via this wizard or manually)."""
        self.ensure_one()
        created = self.env["mrp.bom"]
        skipped = self.env["purchase.request.bom.bootstrap.line"]
        bom_model = self.env["mrp.bom"]
        for line in self.line_ids:
            if line.status != "ok" or line.bom_id:
                continue
            template = line.product_tmpl_id
            if bom_model.search_count(
                [
                    ("product_tmpl_id", "=", template.id),
                    ("active", "=", True),
                    ("type", "=", "normal"),
                ]
            ):
                skipped |= line
                continue
            bom = bom_model.create(
                {
                    "product_tmpl_id": template.id,
                    "product_qty": 1.0,
                    "product_uom_id": template.uom_id.id,
                    "type": "normal",
                    "active": True,
                    "is_bootstrap": True,
                }
            )
            bom_lines = []
            for component in line.component_ids:
                bom_lines.append(
                    (
                        0,
                        0,
                        {
                            "product_id": component.id,
                            "product_qty": 1.0,
                            "product_uom_id": component.uom_id.id,
                        },
                    )
                )
            bom.write({"bom_line_ids": bom_lines})
            template.message_post(
                body=_(
                    "Draft BOM generated by the bootstrap wizard from "
                    "product code pattern. Review required before use."
                )
            )
            line.bom_id = bom.id
            created |= bom

        if not created:
            raise UserError(
                _(
                    "No BOM was generated. Run the preview first and make "
                    "sure matched products are selected."
                )
            )

        summary = _("Generated %(count)s draft BOM(s) with %(component_count)s "
                    "components. Review them in Manufacturing > Products > "
                    "Bills of Materials.") % {
            "count": len(created),
            "component_count": len(created.mapped("bom_line_ids")),
        }
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom",
            "view_mode": "tree,form",
            "name": _("Generated Draft BOMs"),
            "domain": [("id", "in", created.ids)],
            "context": {"search_default_is_bootstrap": True},
        }


class PurchaseRequestBomBootstrapLine(models.TransientModel):
    _name = "purchase.request.bom.bootstrap.line"
    _description = "Bootstrap BOM Wizard Line"

    wizard_id = fields.Many2one(
        comodel_name="purchase.request.bom.bootstrap",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template", string="MX Product", required=True
    )
    product_code = fields.Char(
        string="Product Code", related="product_tmpl_id.default_code", readonly=True
    )
    product_name = fields.Char(
        string="Product Name", related="product_tmpl_id.name", readonly=True
    )
    component_ids = fields.Many2many(
        comodel_name="product.product", string="Components Found"
    )
    component_codes = fields.Char(
        string="Component Codes",
        compute="_compute_component_codes",
        readonly=True,
    )
    status = fields.Selection(
        [("ok", "Match Found"), ("no_match", "No Match")],
        string="Status",
        default="no_match",
        readonly=True,
    )
    bom_id = fields.Many2one(
        comodel_name="mrp.bom", string="Generated BOM", readonly=True
    )

    @api.depends("component_ids.default_code")
    def _compute_component_codes(self):
        for line in self:
            line.component_codes = ", ".join(
                line.component_ids.mapped("default_code")
            )
