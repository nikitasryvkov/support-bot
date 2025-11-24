Operational notes and design decisions:

- Language detection: bot uses Telegram's language_code as first guess, then persisted per-user in Redis. Users can change via /language.
- Ticket mapping: when a user's message is forwarded to the support group the forwarded message_id is mapped to ticket id. Operators must reply to that forwarded message for the bot to route responses back.
- Encryption: uses Fernet to encrypt "content" field. If FERNET_KEY not provided the bot stores plain text (not recommended).
- Backups: simple script uses redis SAVE and copies dump.rdb. For production consider scheduled backups (CronJob) and offsite storage.
- Scaling: bot, reminders, admin are separate services. Redis centralizes state. For higher throughput you can shard or partition.
- Reminders: configurable intervals. Worker bumps ticket timestamps after notifying to avoid repeated spam.
- Admin notifications: admin app calls Telegram Bot API directly to send messages to users.

Limitations & TODO:
- No authentication on admin UI (add OAuth or simple token).
- No file attachments persistence beyond Telegram forwarding.
- No webhooks; currently uses long polling (suitable for many setups but webhooks recommended for large scale).
- Operator presence and concurrency management are basic; consider locking if multiple operators respond simultaneously.

Contact:
Provided BOT_DEV_ID will receive critical errors and reminder escalations.