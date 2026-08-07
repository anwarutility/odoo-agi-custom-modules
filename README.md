# Odoo AGI Custom Modules

Private repo untuk backup modul custom Odoo 16 milik PT Aston Graphindo Indonesia.

## Modules

- **purchase_request_auto_rfq** — Auto-generate draft RFQs from approved Purchase Requests with BOM breakdown
- **purchase_request_telegram_notify** — Telegram notifications for PR approval based on HR manager hierarchy

## Update Workflow

```bash
cd ~/backup-odoo-modules
cp -r /opt/odoo/custom-addons/purchase_request_auto_rfq .
cp -r /opt/odoo/custom-addons/purchase_request_telegram_notify .
git add .
git status
git commit -m "Update: <description>"
git push
```
