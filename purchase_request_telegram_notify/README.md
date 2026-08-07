# Purchase Request Telegram Notification

Odoo 16 module: Send Telegram notifications for Purchase Request approval,
routing approvals based on **HR manager hierarchy** (override rules first,
then manager chain).

## Dependencies

- `purchase_request` (OCA)
- `hr`

## Features

- **Trigger A**: When a PR enters `to_approve` state, Telegram notification
  is sent to the appropriate approver.
- **Trigger B**: When a PR reaches `approved` or `rejected` state,
  Telegram notification is sent to the requester.
- **Approver resolution** (priority order):
  1. Active Override Rule matching the requester
  2. Direct manager (`hr.employee.parent_id`)
  3. If requester is a top-level manager (self-referencing parent):
     - Anton: notify self only
     - Anwar/Danar: notify self + cc Anton
  4. Fallback (no employee record, no manager): broadcast to top-3 managers

## Setup

### 1. Telegram Bot Token

After installing the module, store the bot token in system parameters:

```bash
# Via Odoo shell
sudo -u odoo odoo shell -d <database> --no-http -c /etc/odoo/odoo.conf
>>> env["ir.config_parameter"].sudo().set_param(
...     "purchase_request_telegram_notify.bot_token",
...     "<YOUR_BOT_TOKEN>")
>>> env.cr.commit()
```

Or via Odoo UI: Settings > Technical > System Parameters.

### 2. Register User Chat IDs

Each user who should receive Telegram notifications must register:

1. Chat `/start` to the bot on Telegram
2. Admin retrieves the `chat_id`:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Find `"chat":{"id":<CHAT_ID>}` in the response.
3. Admin opens the user form in Odoo, goes to tab "Telegram Notification",
   and fills in the `Telegram Chat ID` field.

### 3. Configure Approval Override Rules

Menu: **Purchase > Approval Override** (only visible to Administrators).

| Field | Description |
|-------|-------------|
| Name | Label for this rule |
| Requesters (Staff) | Employees whose PRs match this rule |
| Approvers (Notified Users) | Users who receive the notification |
| Active | Enable/disable this rule |

**Pre-seeded data:**
- `Febriyan - Purchasing`: Febriyan's PRs → notified to Hary Purwoko (active)
- `Telesales Group - Satriyo/Nashirudin`: inactive, needs manual configuration

## Changing the Bot Token

Update via System Parameters or shell:
```bash
sudo -u odoo odoo shell -d <database> --no-http
>>> env["ir.config_parameter"].sudo().set_param(
...     "purchase_request_telegram_notify.bot_token", "<NEW_TOKEN>")
>>> env.cr.commit()
```

No restart required — the token is read on every notification send.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| No notification sent | Verify token is set in System Parameters |
| Notification not sent to specific user | Check user has `Telegram Chat ID` filled |
| Message appears in chatter: "User X has no Telegram Chat ID" | Register the user's chat_id |
| "Telegram notification failed: API error" | Verify bot token is valid, server can reach `api.telegram.org` |
| Approval button feels slow | Multiple recipients + Telegram API timeout can add 10-20s worst case |

## Future Enhancements

- Auto `chat_id` registration via cron polling `getUpdates` with `/start` auto-reply

## License

LGPL-3
