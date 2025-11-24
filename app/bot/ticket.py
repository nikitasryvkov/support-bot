import os
import time
import json
import redis
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)

FERNET_KEY = os.getenv("FERNET_KEY")
fernet = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None

# Keys:
# ticket:next -> INCR for ticket ids
# ticket:{id} -> hash with fields
# mapping:forwarded:{group_msg_id} -> ticket_id
# tickets:open -> set of open ticket ids
# tickets:updated -> zset with last_updated timestamps

def _encrypt(s: str):
    if not s:
        return ""
    if not fernet:
        return s
    return fernet.encrypt(s.encode()).decode()

def _decrypt(s: str):
    if not s:
        return ""
    if not fernet:
        return s
    try:
        return fernet.decrypt(s.encode()).decode()
    except Exception:
        return s

def create_ticket(user_id: int, username: str, lang: str, text: str, forwarded_group_msg=None):
    tid = r.incr("ticket:next")
    key = f"ticket:{tid}"
    now = int(time.time())
    payload = {
        "id": str(tid),
        "user_id": str(user_id),
        "username": username or "",
        "lang": lang or "",
        "status": "new",
        "created_at": str(now),
        "updated_at": str(now),
        "content_enc": _encrypt(text),
        "group_message_id": str(forwarded_group_msg or ""),
    }
    r.hset(key, mapping=payload)
    r.sadd("tickets:open", tid)
    r.zadd("tickets:updated", {tid: now})
    return tid

def get_ticket(tid):
    key = f"ticket:{tid}"
    data = r.hgetall(key)
    if not data:
        return None
    data["content"] = _decrypt(data.get("content_enc", ""))
    return data

def set_status(tid, status):
    key = f"ticket:{tid}"
    now = int(time.time())
    r.hset(key, "status", status)
    r.hset(key, "updated_at", str(now))
    if status == "resolved":
        r.srem("tickets:open", tid)
        r.zrem("tickets:updated", tid)
    else:
        r.sadd("tickets:open", tid)
        r.zadd("tickets:updated", {tid: now})

def add_group_mapping(group_msg_id, tid):
    r.set(f"mapping:forwarded:{group_msg_id}", tid)

def get_ticket_id_by_group_msg(group_msg_id):
    return r.get(f"mapping:forwarded:{group_msg_id}")

def update_ticket_timestamp(tid):
    now = int(time.time())
    r.hset(f"ticket:{tid}", "updated_at", str(now))
    r.zadd("tickets:updated", {tid: now})

def list_open_tickets():
    ids = r.smembers("tickets:open")
    return list(ids)

def list_all_tickets(limit=100):
    keys = r.keys("ticket:*")
    tickets = []
    for k in keys:
        if k == "ticket:next":
            continue
        tickets.append(r.hgetall(k))
    return tickets