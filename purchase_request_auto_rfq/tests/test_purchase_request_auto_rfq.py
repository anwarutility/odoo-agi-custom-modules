# Copyright 2026 PT Aston Graphindo Indonesia
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchaseRequestAutoRfq(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking = cls.env.ref("stock.picking_type_in")
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.partner_a = cls.env["res.partner"].create({"name": "Vendor A"})
        cls.partner_b = cls.env["res.partner"].create({"name": "Vendor B"})
        cls.partner_c = cls.env["res.partner"].create({"name": "Vendor C"})

    @classmethod
    def _mk_product(cls, code, vendor=None, min_qty=1.0):
        product = cls.env["product.product"].create(
            {
                "name": code,
                "default_code": code,
                "type": "product",
                "uom_id": cls.uom_unit.id,
                "uom_po_id": cls.uom_unit.id,
            }
        )
        if vendor:
            cls.env["product.supplierinfo"].create(
                {
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "partner_id": vendor.id,
                    "min_qty": min_qty,
                    "sequence": 1,
                }
            )
        return product

    @classmethod
    def _mk_bom(cls, fg_product, components, product_qty=1.0, sequence=1):
        return cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": fg_product.product_tmpl_id.id,
                "product_qty": product_qty,
                "sequence": sequence,
                "type": "normal",
                "bom_line_ids": [
                    (0, 0, {
                        "product_id": comp.id,
                        "product_qty": qty,
                        "product_uom_id": cls.uom_unit.id,
                    })
                    for comp, qty in components
                ],
            }
        )

    def _mk_pr(self, lines, approve=True):
        pr = self.env["purchase.request"].create(
            {
                "picking_type_id": self.picking.id,
                "line_ids": [
                    (0, 0, {
                        "product_id": product.id,
                        "product_qty": qty,
                        "product_uom_id": self.uom_unit.id,
                    })
                    for product, qty in lines
                ],
            }
        )
        if approve:
            pr.button_to_approve()
            pr.button_approved()
        return pr

    def _pos(self, pr):
        return pr.mapped("line_ids.purchase_lines.order_id")

    # --- scenario 1: BOM breakdown with ratio scaling -------------------
    def test_01_bom_breakdown_ratio(self):
        fg = self._mk_product("MX-TEST01", vendor=self.partner_c)
        comp = self._mk_product("COMP-TEST01A", vendor=self.partner_a)
        box = self._mk_product("BOX_TEST01B", vendor=self.partner_b)
        self._mk_bom(fg, [(comp, 1.0), (box, 2.0)], product_qty=2.0)
        pr = self._mk_pr([(fg, 5.0)])
        pos = self._pos(pr)
        self.assertEqual(len(pos), 2, "two vendors -> two RFQs")
        by_vendor = {po.partner_id: po for po in pos}
        # ratio 5/2 = 2.5 -> comp qty 2.5 rounded to 3.0 by the Unit UoM
        self.assertEqual(by_vendor[self.partner_a].order_line.product_qty, 3.0)
        self.assertEqual(by_vendor[self.partner_b].order_line.product_qty, 5.0)

    # --- scenario 2: ORI- pass-through ---------------------------------
    def test_02_ori_pass_through(self):
        ori = self._mk_product("ORI-TEST02", vendor=self.partner_a)
        pr = self._mk_pr([(ori, 2.0)])
        po = self._pos(pr)
        self.assertEqual(len(po), 1)
        self.assertEqual(po.partner_id, self.partner_a)
        self.assertEqual(po.order_line.product_id, ori)
        self.assertEqual(po.order_line.product_qty, 2.0)

    # --- scenario 3: mixed multi-vendor -> multiple RFQs ---------------
    def test_03_mixed_multi_vendor(self):
        fg = self._mk_product("MX-TEST03", vendor=self.partner_c)
        comp = self._mk_product("COMP-TEST03A", vendor=self.partner_a)
        box = self._mk_product("BOX_TEST03B", vendor=self.partner_b)
        ori = self._mk_product("ORI-TEST03", vendor=self.partner_c)
        self._mk_bom(fg, [(comp, 1.0), (box, 1.0)])
        pr = self._mk_pr([(fg, 1.0), (ori, 1.0)])
        pos = self._pos(pr)
        self.assertEqual(len(pos), 3, "A + B + C -> three RFQs")
        vendors = {po.partner_id for po in pos}
        self.assertEqual(
            vendors, {self.partner_a, self.partner_b, self.partner_c}
        )
        for po in pos:
            self.assertTrue(
                po.order_line.purchase_request_lines, "PO line must be linked"
            )
            self.assertTrue(
                po.order_line.purchase_request_allocation_ids,
                "PO line must have an allocation",
            )

    # --- scenario 4: MX- without BOM -> skip + warning -----------------
    def test_04_mx_without_bom(self):
        fg = self._mk_product("MX-TEST04", vendor=self.partner_a)
        pr = self._mk_pr([(fg, 1.0)])
        self.assertEqual(len(self._pos(pr)), 0, "no RFQ without BOM")
        bodies = " ".join(m.body or "" for m in pr.message_ids)
        self.assertIn("belum punya BOM", bodies)

    # --- scenario 5: approve -> reject -> approve : no duplicate -------
    def test_05_no_duplicate_on_reapprove(self):
        fg = self._mk_product("MX-TEST05", vendor=self.partner_a)
        comp = self._mk_product("COMP-TEST05A", vendor=self.partner_a)
        self._mk_bom(fg, [(comp, 1.0)])
        pr = self._mk_pr([(fg, 1.0)])
        self.assertEqual(len(self._pos(pr)), 1)
        first = self._pos(pr)
        pr.write({"state": "rejected"})
        pr.write({"state": "approved"})
        self.assertEqual(
            self._pos(pr), first, "re-approval must not create duplicates"
        )
        self.assertEqual(pr.rfq_count, 1)

    # --- scenario 6: multiple active BOMs -> sequence decides ----------
    def test_06_multiple_boms_sequence(self):
        fg = self._mk_product("MX-TEST06", vendor=self.partner_a)
        low = self._mk_product("COMP-TEST06LOW", vendor=self.partner_a)
        high = self._mk_product("COMP-TEST06HIGH", vendor=self.partner_a)
        self._mk_bom(fg, [(low, 1.0)], sequence=1)
        self._mk_bom(fg, [(high, 1.0)], sequence=10)
        pr = self._mk_pr([(fg, 1.0)])
        po = self._pos(pr)
        self.assertEqual(len(po), 1)
        self.assertEqual(po.order_line.product_id, low)

    # --- scenario 7: unknown prefix -> pass-through --------------------
    def test_07_unknown_prefix_pass_through(self):
        unknown = self._mk_product("XYZ-TEST07", vendor=self.partner_b)
        pr = self._mk_pr([(unknown, 3.0)])
        po = self._pos(pr)
        self.assertEqual(len(po), 1)
        self.assertEqual(po.order_line.product_id, unknown)
        self.assertEqual(po.order_line.product_qty, 3.0)

    # --- scenario 8: component without vendor -> skip + warning --------
    def test_08_component_without_vendor(self):
        fg = self._mk_product("MX-TEST08", vendor=self.partner_a)
        comp = self._mk_product("COMP-TEST08A")
        self._mk_bom(fg, [(comp, 1.0)])
        pr = self._mk_pr([(fg, 1.0)])
        self.assertEqual(len(self._pos(pr)), 0, "no RFQ without vendor")
        bodies = " ".join(m.body or "" for m in pr.message_ids)
        self.assertIn("tidak punya vendor", bodies)

    # --- scenario 9: deleted RFQ -> manual button regenerates ----------
    def test_09_manual_regeneration(self):
        fg = self._mk_product("MX-TEST09", vendor=self.partner_a)
        comp = self._mk_product("COMP-TEST09A", vendor=self.partner_a)
        self._mk_bom(fg, [(comp, 1.0)])
        pr = self._mk_pr([(fg, 1.0)])
        self.assertEqual(len(self._pos(pr)), 1)
        self._pos(pr).button_cancel()
        self._pos(pr).unlink()
        self.assertEqual(pr.rfq_count, 0)
        action = pr.action_generate_rfq()
        self.assertEqual(len(self._pos(pr)), 1, "manual button regenerates")
        self.assertEqual(pr.rfq_count, 1)
        self.assertTrue(action["domain"])

    # --- scenario 10: action_generate_rfq only when approved -----------
    def test_10_manual_button_requires_approved(self):
        fg = self._mk_product("MX-TEST10", vendor=self.partner_a)
        comp = self._mk_product("COMP-TEST10A", vendor=self.partner_a)
        self._mk_bom(fg, [(comp, 1.0)])
        pr = self._mk_pr([(fg, 1.0)], approve=False)
        with self.assertRaises(Exception):
            pr.action_generate_rfq()

    # --- scenario 11: BN_ bonus code -> lookup product used ------------
    def test_11_bn_lookup_found(self):
        target = self._mk_product("ORI-TEST11", vendor=self.partner_a)
        bn = self._mk_product("BN_ORI-TEST11")
        pr = self._mk_pr([(bn, 2.0)])
        po = self._pos(pr)
        self.assertEqual(len(po), 1)
        self.assertEqual(po.order_line.product_id, target)
        self.assertEqual(po.order_line.product_qty, 2.0)
        self.assertEqual(po.partner_id, self.partner_a)
        po = self._pos(pr)
        pr.write({"state": "rejected"})
        pr.write({"state": "approved"})
        self.assertEqual(self._pos(pr), po, "BN- line must not duplicate")

    # --- scenario 12: BN_ without lookup -> skip + warning -------------
    def test_12_bn_lookup_missing(self):
        bn = self._mk_product("BN_GHOST-TEST12")
        pr = self._mk_pr([(bn, 1.0)])
        self.assertEqual(len(self._pos(pr)), 0)
        bodies = " ".join(m.body or "" for m in pr.message_ids)
        self.assertIn("tidak ditemukan", bodies)

    # --- scenario 13: BN_MX_ -> BOM of the lookup MX product -----------
    def test_13_bn_mx_breakdown(self):
        fg = self._mk_product("MX-TEST13", vendor=self.partner_c)
        comp = self._mk_product("COMP-TEST13A", vendor=self.partner_a)
        self._mk_bom(fg, [(comp, 1.0)])
        bn = self._mk_product("BN_MX-TEST13")
        pr = self._mk_pr([(bn, 1.0)])
        po = self._pos(pr)
        self.assertEqual(len(po), 1)
        self.assertEqual(po.order_line.product_id, comp)
        self.assertEqual(po.order_line.product_qty, 1.0)

    # --- scenario 14: RFQ buyer = user with login harypurwoko ----------
    def test_14_rfq_buyer_harypurwoko(self):
        buyer = self.env["res.users"].search(
            [("login", "=", "harypurwoko")], limit=1
        )
        if not buyer:
            buyer = self.env["res.users"].create(
                {"name": "Hary Purwoko", "login": "harypurwoko"}
            )
        ori = self._mk_product("ORI-TEST14", vendor=self.partner_a)
        pr = self._mk_pr([(ori, 1.0)])
        po = self._pos(pr)
        self.assertEqual(len(po), 1)
        self.assertEqual(po.user_id, buyer)

    # --- scenario 15: buyer missing -> default buyer + warning ---------
    def test_15_rfq_buyer_missing_fallback(self):
        buyer = self.env["res.users"].search(
            [("login", "=", "harypurwoko")], limit=1
        )
        self.assertTrue(buyer, "test requires the harypurwoko user")
        buyer.write({"active": False})
        try:
            ori = self._mk_product("ORI-TEST15", vendor=self.partner_a)
            pr = self._mk_pr([(ori, 1.0)])
            po = self._pos(pr)
            self.assertEqual(len(po), 1)
            self.assertEqual(po.user_id, self.env.user,
                             "fallback must keep the default buyer")
            bodies = " ".join(m.body or "" for m in pr.message_ids)
            self.assertIn("harypurwoko", bodies)
            self.assertIn("buyer default", bodies)
        finally:
            buyer.write({"active": True})
