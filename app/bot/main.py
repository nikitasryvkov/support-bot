import os
import logging
import traceback
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, executor
from aiogram.utils.exceptions import TelegramAPIError
from i18n import I18n
from ticket import create_ticket, get_ticket, set_status, add_group_mapping, get_ticket_id_by_group_msg, update_ticket_timestamp
import ticket as ticket_module

load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN not set in env")

BOT_DEV_ID = int(os.getenv("BOT_DEV_ID", "0"))
BOT_GROUP_ID = int(os.getenv("BOT_GROUP_ID", "0"))

EMOJI_NEW = os.getenv("EMOJI_NEW", "🆕")
EMOJI_IN_PROGRESS = os.getenv("EMOJI_IN_PROGRESS", "🔵")
EMOJI_RESOLVED = os.getenv("EMOJI_RESOLVED", "✅")

DEFAULT_LANG = os.getenv("DEFAULT_LANG", "ru")

i18n = I18n(locales_path="locales", default=DEFAULT_LANG)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Simple in-memory user language preference fallback: stored in Redis per-ticket; we can also store user:lang
import redis, os
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)

def set_user_lang(user_id, lang):
    r.set(f"user:lang:{user_id}", lang)

def get_user_lang(user_id):
    v = r.get(f"user:lang:{user_id}")
    return v or DEFAULT_LANG

@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    lang = message.from_user.language_code or get_user_lang(message.from_user.id) or DEFAULT_LANG
    set_user_lang(message.from_user.id, lang)
    await message.answer(i18n.t("welcome", lang=lang))
    await message.answer(i18n.t("help_short", lang=lang))

@dp.message_handler(commands=["language"])
async def cmd_language(message: types.Message):
    lang = get_user_lang(message.from_user.id)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("Русский 🇷🇺", "English 🇺🇸")
    await message.answer(i18n.t("choose_language", lang=lang), reply_markup=kb)

@dp.message_handler(lambda m: m.text in ["Русский 🇷🇺", "English 🇺🇸"])
async def lang_choice(message: types.Message):
    if message.text.startswith("Рус"):
        lang = "ru"
    else:
        lang = "en"
    set_user_lang(message.from_user.id, lang)
    await message.answer(i18n.t("language_set", lang=lang), reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(commands=["mytickets"])
async def my_tickets(message: types.Message):
    lang = get_user_lang(message.from_user.id)
    # list user's tickets (simple scan)
    keys = r.keys("ticket:*")
    user_tickets = []
    for k in keys:
        if k == "ticket:next":
            continue
        t = r.hgetall(k)
        if t.get("user_id") == str(message.from_user.id):
            user_tickets.append(t)
    if not user_tickets:
        await message.answer(i18n.t("no_tickets", lang=lang))
        return
    texts = []
    for t in user_tickets:
        emoji = EMOJI_NEW if t.get("status") == "new" else (EMOJI_IN_PROGRESS if t.get("status") == "in_progress" else EMOJI_RESOLVED)
        texts.append(i18n.t("ticket_line", lang=lang, id=t.get("id"), emoji=emoji, status=t.get("status"), created=t.get("created_at")))
    await message.answer("\n".join(texts))

@dp.message_handler()
async def handle_user_message(message: types.Message):
    try:
        user = message.from_user
        lang = get_user_lang(user.id) or (user.language_code or DEFAULT_LANG)
        set_user_lang(user.id, lang)
        text = message.text or "<media>"
        # Create ticket
        tid = create_ticket(user_id=user.id, username=user.username or "", lang=lang, text=text)
        # Forward to support group and remember mapping
        forwarded = await bot.forward_message(chat_id=BOT_GROUP_ID, from_chat_id=message.chat.id, message_id=message.message_id)
        add_group_mapping(forwarded.message_id, tid)
        # store group message id in ticket
        r.hset(f"ticket:{tid}", "group_message_id", str(forwarded.message_id))
        # Notify user
        await message.answer(i18n.t("ticket_created", lang=lang, id=tid, emoji=EMOJI_NEW))
        # notify operators in group with context
        await bot.send_message(BOT_GROUP_ID, i18n.t("new_ticket_notification", lang=lang, id=tid, user=user.full_name or user.username or user.id))
    except Exception as e:
        logger.error("Error in handle_user_message: %s", e)
        traceback.print_exc()
        # notify dev
        if BOT_DEV_ID:
            try:
                await bot.send_message(BOT_DEV_ID, f"Error while creating ticket: {e}")
            except Exception:
                pass

@dp.message_handler(lambda message: message.chat.type in ["group", "supergroup"])
async def handle_group_messages(message: types.Message):
    # This handles operator replies in the group to forwarded messages
    try:
        if not message.reply_to_message:
            return
        orig = message.reply_to_message
        mapping = await _get_mapping_for_message(orig)
        if not mapping:
            return
        tid = mapping
        t = get_ticket(tid)
        if not t:
            return
        user_id = int(t.get("user_id"))
        # mark in-progress if not yet
        if t.get("status") == "new":
            set_status(tid, "in_progress")
        # Operators can use /resolve command or simply reply to user
        # Forward operator message content to user
        if message.text:
            await bot.send_message(user_id, i18n.t("operator_reply_prefix", lang=t.get("lang")) + "\n" + message.text)
            update_ticket_timestamp(tid)
            await message.reply(i18n.t("posted_to_user", lang=get_user_lang(message.from_user.id)))
        # if attachment, forward media
        elif message.photo or message.document or message.sticker or message.audio or message.video:
            # forward the operator's message to user
            await bot.forward_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            update_ticket_timestamp(tid)
    except Exception as e:
        logger.error("Error in handle_group_messages: %s", e)
        if BOT_DEV_ID:
            try:
                await bot.send_message(BOT_DEV_ID, f"Error in group handler: {e}")
            except Exception:
                pass

async def _get_mapping_for_message(msg: types.Message):
    # mapping is based on group message id (the forwarded id)
    gid = msg.message_id
    tid = ticket_module.r.get(f"mapping:forwarded:{gid}")
    return tid

@dp.message_handler(commands=["resolve"])
async def cmd_resolve(message: types.Message):
    # allow user to resolve their ticket by reply: /resolve <id>
    args = message.get_args().strip()
    lang = get_user_lang(message.from_user.id)
    if not args:
        await message.answer(i18n.t("resolve_usage", lang=lang))
        return
    try:
        tid = args.split()[0]
        t = get_ticket(tid)
        if not t:
            await message.answer(i18n.t("ticket_not_found", lang=lang, id=tid))
            return
        if str(t.get("user_id")) != str(message.from_user.id):
            await message.answer(i18n.t("not_owner", lang=lang))
            return
        set_status(tid, "resolved")
        await message.answer(i18n.t("ticket_resolved", lang=lang, id=tid, emoji=EMOJI_RESOLVED))
        # notify group
        await bot.send_message(BOT_GROUP_ID, i18n.t("ticket_resolved_notify", lang=t.get("lang"), id=tid))
    except TelegramAPIError as e:
        logger.exception("Telegram error: %s", e)
    except Exception as e:
        logger.exception("Error resolving ticket: %s", e)
        if BOT_DEV_ID:
            await bot.send_message(BOT_DEV_ID, f"Error resolving ticket: {e}")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)