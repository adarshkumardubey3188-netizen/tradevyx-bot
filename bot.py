"""
TRADEVYX Contact Bot
---------------------
Features:
- Fully editable Welcome message (text + optional image)
- 1 fixed "Contact" button on its own row
- Fully customizable extra buttons below it (add/edit/delete/reorder any number,
  each with a custom label + custom URL) — arranged 2 per row, in whatever order
  you set via the admin panel
- Fully editable Prompt message shown after tapping Contact (text + optional image)
- Fully editable "Message Sent" confirmation (text + optional image)
- Preserves formatting AND premium/custom emojis exactly as sent, both in user
  messages (via copy_message) and in every admin-edited message (via stored
  Telegram entities, not naive text/Markdown).
  Note: Telegram does not allow formatting/premium emoji inside button labels —
  that's a platform limitation, not something this bot can work around.
- User messages forwarded to admin with date/time, user ID, and a clickable link
  (works even if the user has no username)
- Admin can reply directly to the forwarded message -> reply goes straight to the user
- All settings persisted in SQLite (survives restarts)
- Secret-command based admin unlock (no hardcoded user ID needed)
- Simple in-chat admin panel (/admin)

SETUP:
1. pip install pyTelegramBotAPI
2. Set BOT_TOKEN as an environment variable
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
DB_PATH = os.environ.get("DB_PATH", "tradevyx.db")  # set to /data/tradevyx.db once a Railway Volume is mounted at /data
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_buttons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            url TEXT NOT NULL,
            position INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            first_seen TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS button_icons (
            target TEXT PRIMARY KEY,
            icon_emoji_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            text TEXT,
            photo_id TEXT,
            entities_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS course_contact_button (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            label TEXT,
            url TEXT
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


# ---------------- CUSTOM BUTTONS (fully editable, any count, reorderable) ----------------

def get_custom_buttons():
    conn = db()
    rows = conn.execute(
        "SELECT id, label, url, position FROM custom_buttons ORDER BY position ASC"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "label": r[1], "url": r[2], "position": r[3]} for r in rows]


def add_custom_button(label, url):
    conn = db()
    row = conn.execute("SELECT COALESCE(MAX(position), 0) FROM custom_buttons").fetchone()
    next_pos = (row[0] or 0) + 1
    conn.execute("INSERT INTO custom_buttons (label, url, position) VALUES (?, ?, ?)", (label, url, next_pos))
    conn.commit()
    conn.close()


def update_custom_button(btn_id, label, url):
    conn = db()
    conn.execute("UPDATE custom_buttons SET label=?, url=? WHERE id=?", (label, url, btn_id))
    conn.commit()
    conn.close()


def delete_custom_button(btn_id):
    conn = db()
    conn.execute("DELETE FROM custom_buttons WHERE id=?", (btn_id,))
    conn.commit()
    conn.close()


def move_custom_button(btn_id, direction):
    """direction: 'up' or 'down' -> swaps position with its neighbor in the list."""
    buttons = get_custom_buttons()
    idx = next((i for i, b in enumerate(buttons) if b["id"] == btn_id), None)
    if idx is None:
        return
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(buttons):
        return
    a, b = buttons[idx], buttons[swap_idx]
    conn = db()
    conn.execute("UPDATE custom_buttons SET position=? WHERE id=?", (b["position"], a["id"]))
    conn.execute("UPDATE custom_buttons SET position=? WHERE id=?", (a["position"], b["id"]))
    conn.commit()
    conn.close()


# ---------------- USER TRACKING (for broadcast) ----------------

def track_user(chat_id):
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO users (chat_id, first_seen) VALUES (?, ?)",
        (chat_id, datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_all_user_ids():
    conn = db()
    rows = conn.execute("SELECT chat_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------- BUTTON PREMIUM-EMOJI ICONS (Bot API 9.4 icon_custom_emoji_id) ----------------
# NOTE: This only actually renders if the bot's owner (the account that created the bot
# via BotFather) has an active Telegram Premium subscription. Without Premium, Telegram
# will silently ignore the icon and show the button with text only.

def get_icon(target):
    conn = db()
    row = conn.execute("SELECT icon_emoji_id FROM button_icons WHERE target=?", (target,)).fetchone()
    conn.close()
    return row[0] if row else None


def set_icon(target, icon_emoji_id):
    conn = db()
    conn.execute("""
        INSERT INTO button_icons (target, icon_emoji_id) VALUES (?, ?)
        ON CONFLICT(target) DO UPDATE SET icon_emoji_id = excluded.icon_emoji_id
    """, (target, icon_emoji_id))
    conn.commit()
    conn.close()


def remove_icon(target):
    conn = db()
    conn.execute("DELETE FROM button_icons WHERE target=?", (target,))
    conn.commit()
    conn.close()


# ---------------- COURSES ----------------

def get_courses():
    conn = db()
    rows = conn.execute("SELECT id, name FROM courses ORDER BY id ASC").fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1]} for r in rows]


def get_course(course_id):
    conn = db()
    row = conn.execute(
        "SELECT id, name, text, photo_id, entities_json FROM courses WHERE id=?", (course_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "text": row[2] or "",
        "photo_id": row[3],
        "entities": entities_from_json(row[4]),
    }


def add_course(name):
    conn = db()
    cur = conn.execute("INSERT INTO courses (name, text, photo_id, entities_json) VALUES (?, '', NULL, NULL)", (name,))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_course_content(course_id, text=None, photo_id=None, entities=None):
    conn = db()
    ej = entities_to_json(entities)
    conn.execute(
        "UPDATE courses SET text=?, photo_id=?, entities_json=? WHERE id=?",
        (text, photo_id, ej, course_id)
    )
    conn.commit()
    conn.close()


def delete_course(course_id):
    conn = db()
    conn.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()
    conn.close()


def get_course_contact():
    conn = db()
    row = conn.execute("SELECT label, url FROM course_contact_button WHERE id=1").fetchone()
    conn.close()
    if row:
        return {"label": row[0] or "📞 CONTACT US NOW", "url": row[1] or "https://t.me/Tradevyx"}
    return {"label": "📞 CONTACT US NOW", "url": "https://t.me/Tradevyx"}


def set_course_contact(label, url):
    conn = db()
    conn.execute("""
        INSERT INTO course_contact_button (id, label, url) VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET label = excluded.label, url = excluded.url
    """, (label, url))
    conn.commit()
    conn.close()


# Defaults (used the very first time, before admin edits anything)
DEFAULTS = {
    "welcome": "👋 Welcome to *TRADEVYX*!\nTap the button below to get in touch with us.",
    "button": "📩 Contact Tradevyx",
    "prompt": "✍️ Write your message below.\nTradevyx will reply soon.",
    "sent": "✅ Message sent!",
    "explore_button": "🎓 Explore Course",
    "menu_prompt": "Use the menu below anytime 👇",
    "course_list_header": "📚 *Available Courses*\nTap a course to view details:",
    "course_empty": "📚 No courses available yet. Check back soon!",
    "course_unavailable": "⚠️ This course is no longer available.",
    "course_back": "⬅️ Back to Courses",
}

# ---------------- STATE ----------------
# in-memory runtime state (who is doing what right now)
user_waiting_for_message = set()          # normal users about to send a message
admin_editing = {}                        # admin_chat_id -> which setting key is being edited
button_edit_state = {}                    # admin_chat_id -> {"mode": "add"/"edit", "id": id_or_None, "step": "label"/"url", "label": temp}
broadcast_state = {}                      # admin_chat_id -> {"step": "awaiting_message"/"confirm", "message_id": int}
icon_edit_state = {}                      # admin_chat_id -> target string ("contact" or "btn_<id>")
course_edit_state = {}                    # admin_chat_id -> {"mode": "add"/"edit", "id": id_or_None, "step": "name"/"content"}
course_contact_edit_state = {}            # admin_chat_id -> {"step": "label"/"url", "label": temp}

EDITABLE_KEYS = {
    "1": ("welcome", "Welcome Message"),
    "2": ("button", "Contact Button Text"),
    "3": ("prompt", "Prompt Message"),
    "4": ("sent", "\"Message Sent\" Confirmation"),
    "5": ("explore_button", "Explore Course Button Text (fixed menu)"),
    "6": ("menu_prompt", "Persistent Menu Message"),
    "7": ("course_list_header", "Course List Header Message"),
    "8": ("course_empty", "\"No Courses Yet\" Message"),
    "9": ("course_unavailable", "\"Course Unavailable\" Message"),
    "10": ("course_back", "\"Back to Courses\" Button Text"),
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


def build_main_markup_json():
    """Row 1: Contact button (full width). Then: all custom buttons, 2 per row.
    Built as a raw JSON dict (not telebot's InlineKeyboardButton class) so we can
    attach icon_custom_emoji_id — a Bot API 9.4 field pyTelegramBotAPI's typed
    classes may not expose yet, but the Bot API server itself understands it."""
    rows = []

    contact_label = get_setting("button", DEFAULTS["button"])["text"]
    contact_btn = {"text": contact_label, "callback_data": "contact_click"}
    contact_icon = get_icon("contact")
    if contact_icon:
        contact_btn["icon_custom_emoji_id"] = contact_icon
    rows.append([contact_btn])

    # Explore Course now lives as a persistent reply keyboard button (see
    # send_persistent_menu) instead of an inline button here.

    row = []
    for btn in get_custom_buttons():
        b = {"text": btn["label"], "url": btn["url"]}
        icon = get_icon(f"btn_{btn['id']}")
        if icon:
            b["icon_custom_emoji_id"] = icon
        row.append(b)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    return json.dumps({"inline_keyboard": rows})


def user_link(user):
    """Clickable link to the user's profile, works even with no username."""
    if user.username:
        return f"https://t.me/{user.username}"
    return f"tg://user?id={user.id}"


def send_persistent_menu(chat_id):
    """Sends the fixed keyboard that stays pinned next to the message box
    (not attached to any single message, unlike inline buttons). Currently
    just holds the Explore Course button. Note: if the admin edits the
    Explore Course button text later, already-open chats keep the old label
    until this is sent again (e.g. next /start) — that's a Telegram
    limitation on reply keyboards, not something the bot can push instantly."""
    explore_label = get_setting("explore_button", DEFAULTS["explore_button"])["text"]
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add(types.KeyboardButton(explore_label))
    send_configured(chat_id, "menu_prompt", reply_markup=markup)


def show_course_list(chat_id):
    track_user(chat_id)
    courses = get_courses()
    if not courses:
        send_configured(chat_id, "course_empty")
        return

    markup = types.InlineKeyboardMarkup()
    for c in courses:
        markup.row(types.InlineKeyboardButton(c["name"], callback_data=f"viewcourse_{c['id']}"))

    send_configured(chat_id, "course_list_header", reply_markup=markup)


# ================= USER SIDE =================

@bot.message_handler(commands=['start'])
def start(message):
    track_user(message.chat.id)
    admin_editing.pop(message.chat.id, None)
    button_edit_state.pop(message.chat.id, None)
    send_configured(message.chat.id, "welcome", reply_markup=build_main_markup_json())
    send_persistent_menu(message.chat.id)


@bot.message_handler(
    func=lambda m: m.text == get_setting("explore_button", DEFAULTS["explore_button"])["text"]
)
def handle_explore_menu_tap(message):
    show_course_list(message.chat.id)


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

@bot.callback_query_handler(func=lambda call: call.data == "contact_click")
def ask_message_callback(call):
    chat_id = call.message.chat.id
    track_user(chat_id)
    user_waiting_for_message.add(chat_id)
    bot.answer_callback_query(call.id)
    send_configured(chat_id, "prompt")


@bot.message_handler(
    func=lambda m: m.chat.id in user_waiting_for_message and not is_admin(m.chat.id),
    content_types=['text', 'photo', 'video', 'document', 'sticker', 'voice', 'audio']
)
def forward_to_admins(message):
    user_waiting_for_message.discard(message.chat.id)
    track_user(message.chat.id)
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

    # FIXED: this now goes through send_configured so formatting/premium emoji/
    # photo on the "Message Sent" confirmation are preserved exactly as edited.
    send_configured(message.chat.id, "sent")


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

def send_admin_panel(chat_id):
    markup = types.InlineKeyboardMarkup()
    for k, (setting_key, label) in EDITABLE_KEYS.items():
        markup.add(types.InlineKeyboardButton(f"✏️ Edit {label}", callback_data=f"edit_{setting_key}"))
    markup.add(types.InlineKeyboardButton("🔘 Manage Extra Buttons (add/edit/reorder)", callback_data="manage_buttons"))
    markup.add(types.InlineKeyboardButton("📚 Manage Courses", callback_data="manage_courses"))
    markup.add(types.InlineKeyboardButton("✏️ Edit Course Contact Button", callback_data="coursecontact_edit"))
    contact_icon_label = "🎨 Change Contact Button Icon" if get_icon("contact") else "🎨 Set Contact Button Premium Icon"
    markup.add(types.InlineKeyboardButton(contact_icon_label, callback_data="seticon_contact"))
    markup.add(types.InlineKeyboardButton("📢 Broadcast Message", callback_data="broadcast_start"))
    markup.add(types.InlineKeyboardButton("👁 Preview Current Settings", callback_data="preview"))
    bot.send_message(chat_id, "🛠 *Tradevyx Admin Panel*\nChoose what to edit:",
                      parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "⛔ Not authorized. Send the secret unlock command first.")
        return
    send_admin_panel(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == "admin_back")
def cb_admin_back(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    send_admin_panel(call.message.chat.id)


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
        f"- Send plain/formatted text (premium emoji works here!), OR\n"
        f"- Send a photo with a caption (caption becomes the text)\n\n"
        f"This will replace the current version.",
        parse_mode="Markdown"
    )


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


# ---------------- MANAGE CUSTOM BUTTONS ----------------

def build_manage_buttons_markup():
    markup = types.InlineKeyboardMarkup()
    buttons = get_custom_buttons()
    for i, b in enumerate(buttons):
        preview = b["url"] if len(b["url"]) <= 28 else b["url"][:25] + "..."
        markup.row(types.InlineKeyboardButton(f"{b['label']} → {preview}", callback_data="noop"))
        controls = []
        if i > 0:
            controls.append(types.InlineKeyboardButton("⬆️", callback_data=f"btnup_{b['id']}"))
        if i < len(buttons) - 1:
            controls.append(types.InlineKeyboardButton("⬇️", callback_data=f"btndown_{b['id']}"))
        controls.append(types.InlineKeyboardButton("✏️ Edit", callback_data=f"btnedit_{b['id']}"))
        icon_label = "🎨 Icon ✓" if get_icon(f"btn_{b['id']}") else "🎨 Icon"
        controls.append(types.InlineKeyboardButton(icon_label, callback_data=f"seticon_btn_{b['id']}"))
        controls.append(types.InlineKeyboardButton("❌ Delete", callback_data=f"btndel_{b['id']}"))
        markup.row(*controls)
    markup.row(types.InlineKeyboardButton("➕ Add New Button", callback_data="btnadd"))
    markup.row(types.InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_back"))
    return markup


def show_manage_buttons_menu(chat_id):
    bot.send_message(
        chat_id,
        "🔘 *Manage Buttons*\nThese appear below the Contact button, 2 per row, "
        "in the order shown here (use ⬆️⬇️ to reorder):",
        parse_mode="Markdown",
        reply_markup=build_manage_buttons_markup()
    )


@bot.callback_query_handler(func=lambda call: call.data == "manage_buttons")
def cb_manage_buttons(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    show_manage_buttons_menu(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == "noop")
def cb_noop(call):
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "btnadd")
def cb_add_button(call):
    if not is_admin(call.from_user.id):
        return
    button_edit_state[call.message.chat.id] = {"mode": "add", "id": None, "step": "label", "label": None}
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "Send the label text for the new button (plain text only — Telegram "
        "doesn't allow premium emoji or formatting inside buttons):"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("btnedit_"))
def cb_edit_button(call):
    if not is_admin(call.from_user.id):
        return
    btn_id = int(call.data.replace("btnedit_", ""))
    button_edit_state[call.message.chat.id] = {"mode": "edit", "id": btn_id, "step": "label", "label": None}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Send the new label text for this button:")


@bot.callback_query_handler(func=lambda call: call.data.startswith("btndel_"))
def cb_delete_button(call):
    if not is_admin(call.from_user.id):
        return
    btn_id = int(call.data.replace("btndel_", ""))
    delete_custom_button(btn_id)
    bot.answer_callback_query(call.id, "Deleted")
    show_manage_buttons_menu(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("btnup_") or call.data.startswith("btndown_"))
def cb_move_button(call):
    if not is_admin(call.from_user.id):
        return
    direction = "up" if call.data.startswith("btnup_") else "down"
    btn_id = int(call.data.split("_", 1)[1])
    move_custom_button(btn_id, direction)
    bot.answer_callback_query(call.id)
    show_manage_buttons_menu(call.message.chat.id)


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and m.chat.id in button_edit_state,
    content_types=['text']
)
def handle_button_edit_input(message):
    state = button_edit_state[message.chat.id]

    if state["step"] == "label":
        state["label"] = message.text
        state["step"] = "url"
        bot.send_message(message.chat.id, "Now send the URL for this button (must start with http:// or https://):")
        return

    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        bot.send_message(message.chat.id, "⚠️ That doesn't look like a valid URL. Send it again, starting with https://")
        return

    if state["mode"] == "add":
        add_custom_button(state["label"], url)
        bot.send_message(message.chat.id, "✅ Button added!")
    else:
        update_custom_button(state["id"], state["label"], url)
        bot.send_message(message.chat.id, "✅ Button updated!")

    button_edit_state.pop(message.chat.id)
    show_manage_buttons_menu(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == "preview")
def handle_preview(call):
    if not is_admin(call.from_user.id):
        return
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(chat_id, "— Welcome Message (with full button layout) —")
    send_configured(chat_id, "welcome", reply_markup=build_main_markup_json())
    send_persistent_menu(chat_id)
    bot.send_message(chat_id, "— Prompt Message —")
    send_configured(chat_id, "prompt")
    bot.send_message(chat_id, "— Sent Confirmation —")
    send_configured(chat_id, "sent")


# ---------------- BROADCAST ----------------

@bot.callback_query_handler(func=lambda call: call.data == "broadcast_start")
def cb_broadcast_start(call):
    if not is_admin(call.from_user.id):
        return
    broadcast_state[call.message.chat.id] = {"step": "awaiting_message"}
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "📢 Send me the message you want to broadcast now.\n\n"
        "Send it exactly as you want users to see it — text with formatting, "
        "premium emoji, a photo, sticker, whatever. It will be copied to everyone "
        "*exactly as-is*, no re-typing, so nothing will change.",
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and broadcast_state.get(m.chat.id, {}).get("step") == "awaiting_message",
    content_types=['text', 'photo', 'video', 'document', 'sticker', 'voice', 'audio', 'animation']
)
def receive_broadcast_message(message):
    broadcast_state[message.chat.id] = {"step": "confirm", "message_id": message.message_id}
    total = len(get_all_user_ids())

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Yes, send it", callback_data="broadcast_confirm"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel"),
    )
    bot.send_message(
        message.chat.id,
        f"⚠️ This will be sent to *{total}* user(s). Confirm?",
        parse_mode="Markdown",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == "broadcast_cancel")
def cb_broadcast_cancel(call):
    if not is_admin(call.from_user.id):
        return
    broadcast_state.pop(call.message.chat.id, None)
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "🚫 Broadcast cancelled.")


@bot.callback_query_handler(func=lambda call: call.data == "broadcast_confirm")
def cb_broadcast_confirm(call):
    if not is_admin(call.from_user.id):
        return
    admin_chat_id = call.message.chat.id
    state = broadcast_state.pop(admin_chat_id, None)
    bot.answer_callback_query(call.id)

    if not state or "message_id" not in state:
        bot.send_message(admin_chat_id, "⚠️ Nothing to broadcast, try again.")
        return

    bot.send_message(admin_chat_id, "📤 Sending broadcast...")

    sent, failed = 0, 0
    for uid in get_all_user_ids():
        try:
            # copy_message replays the exact content/format/premium-emoji, no retyping
            bot.copy_message(uid, admin_chat_id, state["message_id"])
            sent += 1
        except Exception:
            failed += 1  # user blocked the bot, deleted account, etc.

    bot.send_message(admin_chat_id, f"✅ Broadcast complete.\nSent: {sent}\nFailed: {failed}")


# ---------------- BUTTON PREMIUM EMOJI ICON ----------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("seticon_"))
def cb_set_icon(call):
    if not is_admin(call.from_user.id):
        return
    target = call.data.replace("seticon_", "")  # "contact" or "btn_<id>"
    icon_edit_state[call.message.chat.id] = target
    bot.answer_callback_query(call.id)

    markup = types.InlineKeyboardMarkup()
    if get_icon(target):
        markup.add(types.InlineKeyboardButton("🗑 Remove current icon", callback_data=f"rmicon_{target}"))

    bot.send_message(
        call.message.chat.id,
        "🎨 Send me the *premium emoji* you want as this button's icon — just that "
        "one emoji, nothing else.\n\n"
        "⚠️ Important:\n"
        "• You need an active *Telegram Premium* subscription on the account that "
        "created this bot for this to actually show up.\n"
        "• If you send a normal (non-premium) emoji, Telegram won't accept it as an icon.",
        parse_mode="Markdown",
        reply_markup=markup if get_icon(target) else None
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("rmicon_"))
def cb_remove_icon(call):
    if not is_admin(call.from_user.id):
        return
    target = call.data.replace("rmicon_", "")
    remove_icon(target)
    icon_edit_state.pop(call.message.chat.id, None)
    bot.answer_callback_query(call.id, "Icon removed")
    bot.send_message(call.message.chat.id, "✅ Icon removed from that button.")
    if target == "contact":
        send_admin_panel(call.message.chat.id)
    else:
        show_manage_buttons_menu(call.message.chat.id)


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and m.chat.id in icon_edit_state,
    content_types=['text']
)
def receive_icon_input(message):
    target = icon_edit_state.pop(message.chat.id)

    custom_emoji_id = None
    for e in (message.entities or []):
        if e.type == "custom_emoji":
            custom_emoji_id = e.custom_emoji_id
            break

    if not custom_emoji_id:
        bot.send_message(
            message.chat.id,
            "⚠️ That didn't look like a premium/custom emoji (or it wasn't recognized). "
            "Make sure you're sending an actual Telegram Premium animated emoji, not a "
            "regular one. Try again from the admin panel."
        )
        return

    set_icon(target, custom_emoji_id)
    bot.send_message(message.chat.id, "✅ Icon saved! Send /start to preview the button.")
    if target == "contact":
        send_admin_panel(message.chat.id)
    else:
        show_manage_buttons_menu(message.chat.id)


# ---------------- COURSES: ADMIN MANAGEMENT ----------------

def build_manage_courses_markup():
    markup = types.InlineKeyboardMarkup()
    for c in get_courses():
        markup.row(types.InlineKeyboardButton(f"📖 {c['name']}", callback_data="noop"))
        markup.row(
            types.InlineKeyboardButton("✏️ Edit Content", callback_data=f"courseedit_{c['id']}"),
            types.InlineKeyboardButton("❌ Delete", callback_data=f"coursedel_{c['id']}"),
        )
    markup.row(types.InlineKeyboardButton("➕ Add New Course", callback_data="courseadd"))
    markup.row(types.InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_back"))
    return markup


def show_manage_courses_menu(chat_id):
    bot.send_message(
        chat_id,
        "📚 *Manage Courses*\nThese show up when a user taps \"Explore Course\":",
        parse_mode="Markdown",
        reply_markup=build_manage_courses_markup()
    )


@bot.callback_query_handler(func=lambda call: call.data == "manage_courses")
def cb_manage_courses(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    show_manage_courses_menu(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == "courseadd")
def cb_course_add(call):
    if not is_admin(call.from_user.id):
        return
    course_edit_state[call.message.chat.id] = {"mode": "add", "id": None, "step": "name"}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Send the course name:")


@bot.callback_query_handler(func=lambda call: call.data.startswith("courseedit_"))
def cb_course_edit(call):
    if not is_admin(call.from_user.id):
        return
    course_id = int(call.data.replace("courseedit_", ""))
    course_edit_state[call.message.chat.id] = {"mode": "edit", "id": course_id, "step": "content"}
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "Send the new course details now — text (with formatting/premium emoji works!) "
        "or a photo with a caption, exactly like editing the welcome message."
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("coursedel_"))
def cb_course_delete(call):
    if not is_admin(call.from_user.id):
        return
    course_id = int(call.data.replace("coursedel_", ""))
    delete_course(course_id)
    bot.answer_callback_query(call.id, "Deleted")
    show_manage_courses_menu(call.message.chat.id)


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and m.chat.id in course_edit_state,
    content_types=['text', 'photo']
)
def handle_course_edit_input(message):
    state = course_edit_state[message.chat.id]

    if state["step"] == "name":
        if message.content_type != 'text' or not message.text.strip():
            bot.send_message(message.chat.id, "⚠️ Please send the course name as plain text.")
            return
        name = message.text.strip()
        course_id = add_course(name)
        state["id"] = course_id
        state["step"] = "content"
        bot.send_message(
            message.chat.id,
            f"Now send the course details for *{name}* — text (with formatting/premium "
            f"emoji works!) or a photo with a caption, exactly like editing the welcome message.",
            parse_mode="Markdown"
        )
        return

    # step == "content"
    if message.content_type == 'photo':
        photo_id = message.photo[-1].file_id
        text = message.caption or ""
        update_course_content(state["id"], text=text, photo_id=photo_id, entities=message.caption_entities)
    else:
        update_course_content(state["id"], text=message.text, photo_id=None, entities=message.entities)

    course_edit_state.pop(message.chat.id)
    bot.send_message(message.chat.id, "✅ Course saved!")
    show_manage_courses_menu(message.chat.id)


# ---------------- COURSE CONTACT BUTTON: ADMIN EDIT ----------------

@bot.callback_query_handler(func=lambda call: call.data == "coursecontact_edit")
def cb_course_contact_edit(call):
    if not is_admin(call.from_user.id):
        return
    course_contact_edit_state[call.message.chat.id] = {"step": "label", "label": None}
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "Send the new label text for the course-contact button "
        "(plain text only — no premium emoji/formatting inside buttons):"
    )


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and m.chat.id in course_contact_edit_state,
    content_types=['text']
)
def handle_course_contact_edit_input(message):
    state = course_contact_edit_state[message.chat.id]

    if state["step"] == "label":
        state["label"] = message.text
        state["step"] = "url"
        bot.send_message(message.chat.id, "Now send the URL (must start with http:// or https://):")
        return

    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        bot.send_message(message.chat.id, "⚠️ That doesn't look like a valid URL. Send it again, starting with https://")
        return

    set_course_contact(state["label"], url)
    course_contact_edit_state.pop(message.chat.id)
    bot.send_message(message.chat.id, "✅ Course contact button updated!")
    send_admin_panel(message.chat.id)


# ---------------- COURSES: USER-FACING ----------------

@bot.callback_query_handler(func=lambda call: call.data == "explore_courses")
def cb_explore_courses(call):
    bot.answer_callback_query(call.id)
    show_course_list(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("viewcourse_"))
def cb_view_course(call):
    chat_id = call.message.chat.id
    track_user(chat_id)
    course_id = int(call.data.replace("viewcourse_", ""))
    course = get_course(course_id)
    bot.answer_callback_query(call.id)

    if not course:
        send_configured(chat_id, "course_unavailable")
        return

    contact = get_course_contact()
    back_label = get_setting("course_back", DEFAULTS["course_back"])["text"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(contact["label"], url=contact["url"]))
    markup.add(types.InlineKeyboardButton(back_label, callback_data="backtocourses"))

    entities = course.get("entities")
    if course["photo_id"]:
        if entities:
            bot.send_photo(chat_id, course["photo_id"], caption=course["text"],
                            caption_entities=entities, reply_markup=markup)
        else:
            bot.send_photo(chat_id, course["photo_id"], caption=course["text"],
                            parse_mode="Markdown", reply_markup=markup)
    else:
        if entities:
            bot.send_message(chat_id, course["text"], entities=entities, reply_markup=markup)
        else:
            bot.send_message(chat_id, course["text"], parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "backtocourses")
def cb_back_to_courses(call):
    bot.answer_callback_query(call.id)
    show_course_list(call.message.chat.id)


print("Tradevyx bot running...")
bot.infinity_polling()
