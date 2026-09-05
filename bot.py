"""
TRADEVYX Contact Bot
---------------------
Features:
- Fully editable Welcome message (text + optional image)
- Fully editable "Contact Tradevyx" button text
- Fully editable Prompt message shown after tapping the button (text + optional image)
- Preserves formatting AND premium/custom emojis exactly as sent (uses copy_message,
  never re-types text)
- User messages forwarded to admin with date/time, user ID, and a clickable link
  (works even if the user has no username)
- Admin can reply directly to the forwarded message -> reply goes straight to the user
- All settings persisted in SQLite (survives restarts)
- Simple in-chat admin panel (/admin)

SETUP:
1. pip install pyTelegramBotAPI
2. Fill in BOT_TOKEN and ADMIN_ID below
3. Run: python bot.py
"""

import sqlite3
import datetime
import os
import json
import telebot
from telebot import types

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # set this in Railway's Variables tab
DB_PATH = "tradevyx.db"
SECRET_COMMAND = "/tradevyx_adarsh_bot"  # send this to unlock admin access
# ============================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it in Railway -> Variables.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ---------------- DATABASE ----------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            text TEXT,
            photo_id TEXT,
            entities_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reply_map (
            admin_chat_id INTEGER,
            admin_msg_id INTEGER,
            user_chat_id INTEGER,
            PRIMARY KEY (admin_chat_id, admin_msg_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    # migration: add entities_json column if the DB was created by an older version
    try:
        conn.execute("ALTER TABLE settings ADD COLUMN entities_json TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    return conn


def entities_to_json(entities):
    if not entities:
        return None
    return json.dumps([e.to_dict() for e in entities])


def entities_from_json(data):
    if not data:
        return None
    raw = json.loads(data)
    return [types.MessageEntity.de_json(e) for e in raw]


def add_admin(user_id):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def remove_admin(user_id):
    conn = db()
    conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def is_admin(user_id):
    conn = db()
    row = conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None


def all_admin_ids():
    conn = db()
    rows = conn.execute("SELECT user_id FROM admins").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_setting(key, default_text="", default_photo=None):
    conn = db()
    row = conn.execute(
        "SELECT text, photo_id, entities_json FROM settings WHERE key=?", (key,)
    ).fetchone()
    conn.close()
    if row:
        return {
            "text": row[0] or default_text,
            "photo_id": row[1],
            "entities": entities_from_json(row[2]),
        }
    return {"text": default_text, "photo_id": default_photo, "entities": None}


def set_setting(key, text=None, photo_id=None, entities=None):
    conn = db()
    ej = entities_to_json(entities)
    conn.execute("""
        INSERT INTO settings (key, text, photo_id, entities_json) VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            text = COALESCE(excluded.text, settings.text),
            photo_id = excluded.photo_id,
            entities_json = excluded.entities_json
    """, (key, text, photo_id, ej))
    conn.commit()
    conn.close()


def save_reply_map(admin_chat_id, admin_msg_id, user_chat_id):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO reply_map (admin_chat_id, admin_msg_id, user_chat_id) VALUES (?, ?, ?)",
                 (admin_chat_id, admin_msg_id, user_chat_id))
    conn.commit()
    conn.close()


def get_user_from_reply(admin_chat_id, admin_msg_id):
    conn = db()
    row = conn.execute(
        "SELECT user_chat_id FROM reply_map WHERE admin_chat_id=? AND admin_msg_id=?",
        (admin_chat_id, admin_msg_id)
    ).fetchone()
    conn.close()
    return row[0] if row else None


# Defaults (used the very first time, before admin edits anything)
DEFAULTS = {
    "welcome": "👋 Welcome to *TRADEVYX*!\nTap the button below to get in touch with us.",
    "button": "📩 Contact Tradevyx",
    "prompt": "✍️ Write your message below.\nTradevyx will reply soon.",
    "sent": "✅ Message sent!",
}

# ---------------- STATE ----------------
# in-memory runtime state (who is doing what right now)
user_waiting_for_message = set()          # normal users about to send a message
admin_editing = {}                        # admin_chat_id -> which setting key is being edited

EDITABLE_KEYS = {
    "1": ("welcome", "Welcome Message"),
    "2": ("button", "Button Text"),
    "3": ("prompt", "Prompt Message"),
    "4": ("sent", "\"Message Sent\" Confirmation"),
}


# ---------------- HELPERS ----------------

def send_configured(chat_id, key, reply_markup=None):
    """Send a stored setting (text + optional photo) to a chat.
    If the admin's original message had formatting/premium-emoji entities,
    those are replayed exactly. Otherwise falls back to Markdown parsing
    (used only for the hardcoded DEFAULTS before anything has been edited)."""
    cfg = get_setting(key, DEFAULTS.get(key, ""))
    entities = cfg.get("entities")

    if cfg["photo_id"]:
        if entities:
            bot.send_photo(chat_id, cfg["photo_id"], caption=cfg["text"],
                            caption_entities=entities, reply_markup=reply_markup)
        else:
            bot.send_photo(chat_id, cfg["photo_id"], caption=cfg["text"],
                            parse_mode="Markdown", reply_markup=reply_markup)
    else:
        if entities:
            bot.send_message(chat_id, cfg["text"], entities=entities, reply_markup=reply_markup)
        else:
            bot.send_message(chat_id, cfg["text"], parse_mode="Markdown", reply_markup=reply_markup)


def main_keyboard():
    cfg = get_setting("button", DEFAULTS["button"])
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton(cfg["text"]))
    return markup


def user_link(user):
    """Clickable link to the user's profile, works even with no username."""
    if user.username:
        return f"https://t.me/{user.username}"
    return f"tg://user?id={user.id}"


# ================= USER SIDE =================

@bot.message_handler(commands=['start'])
def start(message):
    admin_editing.pop(message.chat.id, None)
    send_configured(message.chat.id, "welcome", reply_markup=main_keyboard())


# ---------------- SECRET UNLOCK ----------------

@bot.message_handler(func=lambda m: m.text == SECRET_COMMAND)
def unlock_admin(message):
    add_admin(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Access granted. You are now an admin.\nUse /admin to open the panel.")


@bot.message_handler(commands=['tradevyx_logout'])
def logout_admin(message):
    if is_admin(message.chat.id):
        remove_admin(message.chat.id)
        bot.send_message(message.chat.id, "🔒 Admin access removed for this account.")
    else:
        bot.send_message(message.chat.id, "You are not an admin.")


# ---------------- USER MESSAGE FLOW ----------------

@bot.message_handler(func=lambda m: (
    not is_admin(m.chat.id)
    and m.text == get_setting("button", DEFAULTS["button"])["text"]
))
def ask_message(message):
    user_waiting_for_message.add(message.chat.id)
    send_configured(message.chat.id, "prompt")


@bot.message_handler(
    func=lambda m: m.chat.id in user_waiting_for_message and not is_admin(m.chat.id),
    content_types=['text', 'photo', 'video', 'document', 'sticker', 'voice', 'audio']
)
def forward_to_admins(message):
    user_waiting_for_message.discard(message.chat.id)
    user = message.from_user
    now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")

    info = (
        f"📩 *New Message*\n"
        f"🕒 {now}\n"
        f"🆔 User ID: `{user.id}`\n"
        f"👤 Profile: {user_link(user)}"
    )

    for admin_id in all_admin_ids():
        bot.send_message(admin_id, info, parse_mode="Markdown")
        # copy_message preserves formatting, premium emojis, and media exactly as sent
        copied = bot.copy_message(admin_id, message.chat.id, message.message_id)
        save_reply_map(admin_id, copied.message_id, message.chat.id)

    cfg = get_setting("sent", DEFAULTS["sent"])
    bot.send_message(message.chat.id, cfg["text"], parse_mode="Markdown")


# ================= ADMIN: REPLYING TO USERS =================

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.reply_to_message is not None)
def admin_reply(message):
    target_chat = get_user_from_reply(message.chat.id, message.reply_to_message.message_id)
    if target_chat:
        bot.copy_message(target_chat, message.chat.id, message.message_id)
        bot.send_message(message.chat.id, "↩️ Reply sent to user.")
    else:
        bot.send_message(message.chat.id, "⚠️ Reply directly to the forwarded user message to route it correctly.")


# ================= ADMIN PANEL =================

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "⛔ Not authorized. Send the secret unlock command first.")
        return
    markup = types.InlineKeyboardMarkup()
    for k, (setting_key, label) in EDITABLE_KEYS.items():
        markup.add(types.InlineKeyboardButton(f"✏️ Edit {label}", callback_data=f"edit_{setting_key}"))
    markup.add(types.InlineKeyboardButton("👁 Preview Current Settings", callback_data="preview"))
    bot.send_message(message.chat.id, "🛠 *Tradevyx Admin Panel*\nChoose what to edit:",
                      parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_"))
def handle_edit_choice(call):
    if not is_admin(call.from_user.id):
        return
    setting_key = call.data.replace("edit_", "")
    admin_editing[call.message.chat.id] = setting_key
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"Send the new content for *{setting_key}* now.\n\n"
        f"- Send plain/formatted text, OR\n"
        f"- Send a photo with a caption (caption becomes the text)\n\n"
        f"This will replace the current version.",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda call: call.data == "preview")
def handle_preview(call):
    if not is_admin(call.from_user.id):
        return
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(chat_id, "— Welcome Message —")
    send_configured(chat_id, "welcome")
    bot.send_message(chat_id, f"— Button Text —\n{get_setting('button', DEFAULTS['button'])['text']}")
    bot.send_message(chat_id, "— Prompt Message —")
    send_configured(chat_id, "prompt")
    bot.send_message(chat_id, "— Sent Confirmation —")
    send_configured(chat_id, "sent")


# This must be registered AFTER admin_reply / admin_panel logic in terms of matching,
# so we guard it with the admin_editing state check.
@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and m.chat.id in admin_editing,
    content_types=['text', 'photo']
)
def receive_new_setting_content(message):
    setting_key = admin_editing.pop(message.chat.id)

    if message.content_type == 'photo':
        photo_id = message.photo[-1].file_id
        text = message.caption or ""
        # caption_entities carries formatting/premium-emoji info for photo captions
        set_setting(setting_key, text=text, photo_id=photo_id, entities=message.caption_entities)
    else:
        # entities carries formatting/premium-emoji info for plain text messages
        set_setting(setting_key, text=message.text, photo_id=None, entities=message.entities)

    label = dict(EDITABLE_KEYS.values()).get(setting_key, setting_key)
    bot.send_message(message.chat.id, f"✅ {label} updated!")


print("Tradevyx bot running...")
bot.infinity_polling()
