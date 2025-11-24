# Telegram Support Bot (multi-service)

This repository contains a production-oriented Telegram support bot with:
- Multi-language support (English, Russian)
- Ticketing system (unique ticket IDs, emoji status)
- Redis-based storage with optional encryption of sensitive fields (Fernet)
- Reminder worker for users and operators
- Simple admin web panel to view/resolve tickets
- Docker Compose setup for easy deployment
- Automatic backups script for Redis snapshot

Architecture:
- bot: Main Telegram bot (Aiogram) — receives messages, creates tickets, forwards to support group
- reminder: Background worker scanner that sends reminders to users/operators
- admin: Minimal Flask admin panel to view and act on tickets
- redis: Storage engine
- backup: One-shot container to trigger Redis SAVE and copy RDB

Environment variables:
- BOT_TOKEN - Telegram bot token (required)
- BOT_DEV_ID - Telegram user id to receive critical notifications
- BOT_GROUP_ID - Telegram group id for support team (forwarded messages)
- EMOJI_NEW / EMOJI_IN_PROGRESS / EMOJI_RESOLVED - Customize emojis
- REDIS_HOST / REDIS_PORT / REDIS_DB / REDIS_PASSWORD
- FERNET_KEY - Base64 key for Fernet encryption (optional but recommended)
- REMINDER_USER_INTERVAL / REMINDER_OPERATOR_INTERVAL - seconds
- DEFAULT_LANG - 'ru' or 'en'
- ADMIN_BIND / ADMIN_PORT - admin panel binding settings

Quick start (development):
1. Copy .env.example to .env and fill values.
2. Start:
   docker compose up --build
3. The admin panel will be available on port 8080 (configurable).

How it works (high level):
- When a user sends any message to the bot, a ticket is created in Redis (ticket:N).
- The user's message is encrypted with Fernet (if FERNET_KEY provided) before storing.
- The bot forwards the original message to the support group; replies by operators to the forwarded message will be routed back to the user.
- Ticket statuses are emoji-marked. Users may use /resolve <ticket_id> to close their ticket.
- Reminder worker periodically scans for stale tickets and notifies user/group/dev accordingly.
- Admin panel allows simple operations (resolve, send message).

Security notes:
- Store FERNET_KEY securely (env or secret manager). It protects sensitive ticket content in Redis dumps.
- Use Docker secrets or a vault in production for BOT_TOKEN & FERNET_KEY.
- The admin panel is intentionally minimal; add authentication for production use.

Extending the bot:
- Add FAQs auto-response by matching incoming text and replying from a knowledge base before creating tickets.
- Add richer admin UI (authentication, filtering, sorting).
- Use persistent message history and analytics to compute SLA times.

Files of interest:
- app/bot (main bot code)
- app/locales (translations)
- app/reminder (reminder worker)
- admin (admin panel)
- backup/backup_redis.sh (backup helper)
- docker-compose.yml - orchestrates services

If you want I can:
- Add more localization strings and a UI for editing them.
- Add pagination and search on admin panel.
- Add webhook support (instead of polling) and TLS termination configuration.