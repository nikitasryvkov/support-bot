import os
from flask import Flask, jsonify, request, render_template_string, redirect, url_for
from dotenv import load_dotenv
import redis
import requests

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_GROUP_ID = os.getenv("BOT_GROUP_ID")
BOT_DEV_ID = os.getenv("BOT_DEV_ID")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)

app = Flask(__name__)

TEMPLATE = '''
<!doctype html>
<title>Support Admin</title>
<h1>Tickets ({{count}})</h1>
<table border="1" cellpadding="6">
<tr><th>ID</th><th>User</th><th>Status</th><th>Created</th><th>Actions</th></tr>
{% for t in tickets %}
<tr>
  <td>{{t.id}}</td>
  <td>{{t.username}} ({{t.user_id}})</td>
  <td>{{t.status}}</td>
  <td>{{t.created_at}}</td>
  <td>
    <form style="display:inline" method="post" action="/admin/resolve/{{t.id}}">
      <button type="submit">Resolve</button>
    </form>
    <form style="display:inline" method="post" action="/admin/comment/{{t.id}}">
      <input name="text" placeholder="Message to user"/>
      <button type="submit">Send</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>
'''

@app.route("/")
def index():
    keys = r.keys("ticket:*")
    tickets = []
    for k in keys:
        if k == "ticket:next": continue
        h = r.hgetall(k)
        tickets.append({
            "id": h.get("id"),
            "user_id": h.get("user_id"),
            "username": h.get("username") or "",
            "status": h.get("status"),
            "created_at": h.get("created_at")
        })
    return render_template_string(TEMPLATE, tickets=tickets, count=len(tickets))

@app.route("/admin/resolve/<tid>", methods=["POST"])
def resolve(tid):
    key = f"ticket:{tid}"
    if not r.exists(key):
        return "Not found", 404
    r.hset(key, "status", "resolved")
    # notify user
    t = r.hgetall(key)
    uid = t.get("user_id")
    send_message(uid, f"Your ticket #{tid} has been marked as resolved by admin.")
    return redirect(url_for('index'))

@app.route("/admin/comment/<tid>", methods=["POST"])
def comment(tid):
    text = request.form.get("text")
    if not text:
        return redirect(url_for('index'))
    key = f"ticket:{tid}"
    if not r.exists(key):
        return "Not found", 404
    t = r.hgetall(key)
    uid = t.get("user_id")
    send_message(uid, f"Admin: {text}")
    return redirect(url_for('index'))

def send_message(chat_id, text):
    if not BOT_TOKEN:
        return
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

if __name__ == "__main__":
    bind = os.getenv("ADMIN_BIND", "0.0.0.0")
    port = int(os.getenv("ADMIN_PORT", "8080"))
    app.run(host=bind, port=port)