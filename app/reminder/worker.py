import os
import time
import traceback
from dotenv import load_dotenv
import redis
import requests

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_GROUP_ID = os.getenv("BOT_GROUP_ID")
BOT_DEV_ID = os.getenv("BOT_DEV_ID")

REMINDER_USER_INTERVAL = int(os.getenv("REMINDER_USER_INTERVAL", "86400"))
REMINDER_OPERATOR_INTERVAL = int(os.getenv("REMINDER_OPERATOR_INTERVAL", "43200"))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_user_message(chat_id, text):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})

def scan_and_remind():
    # tickets:updated zset contains tid -> last updated timestamp
    cutoff_user = int(time.time()) - REMINDER_USER_INTERVAL
    cutoff_op = int(time.time()) - REMINDER_OPERATOR_INTERVAL
    try:
        old_for_users = r.zrangebyscore("tickets:updated", 0, cutoff_user)
        for tid in old_for_users:
            t = r.hgetall(f"ticket:{tid}")
            if not t:
                continue
            if t.get("status") == "resolved":
                continue
            user_id = t.get("user_id")
            lang = t.get("lang") or os.getenv("DEFAULT_LANG", "en")
            text = f"Reminder: your ticket #{tid} is still open. Our team works on it."
            send_user_message(user_id, text)
            # bump so we don't spam many times in same cycle; update timestamp
            now = int(time.time())
            r.zadd("tickets:updated", {tid: now})
        # remind operators: list tickets older than op cutoff
        old_for_ops = r.zrangebyscore("tickets:updated", 0, cutoff_op)
        for tid in old_for_ops:
            t = r.hgetall(f"ticket:{tid}")
            if not t or t.get("status") == "resolved":
                continue
            # send summary to group
            summary = f"Reminder: ticket #{tid} is still open. User: {t.get('username') or t.get('user_id')}"
            if BOT_GROUP_ID:
                send_user_message(BOT_GROUP_ID, summary)
            # notify dev for critical cases (e.g., older than 7 days)
            if int(time.time()) - int(t.get("created_at", "0")) > 7 * 24 * 3600 and BOT_DEV_ID:
                send_user_message(BOT_DEV_ID, f"Critical: ticket #{tid} older than 7 days")
            # bump timestamp to avoid immediate repeat
            now = int(time.time())
            r.zadd("tickets:updated", {tid: now})
    except Exception as e:
        traceback.print_exc()
        if BOT_DEV_ID:
            send_user_message(BOT_DEV_ID, f"Reminder worker error: {e}")

if __name__ == "__main__":
    while True:
        try:
            scan_and_remind()
        except Exception:
            traceback.print_exc()
        time.sleep(60)