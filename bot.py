import os, json, subprocess, threading
from flask import Flask, request, redirect, send_from_directory
from PIL import Image
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- CONFIG (Auto create) ---
os.makedirs("downloads", exist_ok=True)
os.makedirs("database", exist_ok=True)
CONFIG_FILE = "database/config.json"
DEFAULT_CONFIG = {
    "START_MSG": "Hello beo 👋\n\nMain tera Tagda Bot hu:\n🔗 File to Link\n✏️ File Renamer + Thumbnail Resizer\n📥 Video Downloader",
    "RENAMER_MSG": "Video/File bhejo jisko rename karna hai.",
    "RENAMER_ASK_NAME_MSG": "Ab naya naam bhejo with extension. Ex: MyVideo.mp4",
    "THUMBNAIL_MSG": "Ab thumbnail bhejo. Main video ko isi thumbnail ke size pe resize karke set kar dunga 🔥\nAgar thumbnail nahi hai to /skip bhej de.",
    "FILE2LINK_MSG": "Ye le tera direct link beo 👇",
    "DOWNLOADER_MSG": "Link bhej bro (YouTube / Insta / FB / Terabox)",
    "BTN_RENAMER": "✏️ File Renamer",
    "BTN_FILE2LINK": "🔗 File to Link",
    "BTN_DOWNLOADER": "📥 Video Downloader"
}
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)

def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)
def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL") or os.getenv("RAILWAY_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
if BASE_URL and not BASE_URL.startswith("http"):
    BASE_URL = "https://" + BASE_URL
if not BASE_URL:
    BASE_URL = f"http://localhost:{os.getenv('PORT','8000')}"

flask_app = Flask(__name__)
user_state = {}

ADMIN_HTML = """
<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tagda Admin</title>
<style>
body{font-family:sans-serif;background:#0f0f0f;color:white;padding:20px}
input,textarea{width:100%;padding:12px;margin:8px 0;background:#1f1f1f;color:white;border:1px solid #333;border-radius:10px}
label{font-weight:bold;margin-top:15px;display:block;color:#00ff88;font-size:12px}
button{width:100%;padding:15px;background:#00ff88;color:black;border:none;border-radius:10px;font-size:18px;margin-top:20px;font-weight:bold}
.card{background:#1a1a1a;padding:15px;border-radius:15px;margin-bottom:20px;border:1px solid #333}
</style></head>
<body>
<h2>🔥 TRADEVYX ADARSH BOT - ADMIN</h2>
<div class="card"><p><b>Base URL:</b> {{base_url}}</p><p>Yaha se sab editable hai beo. Premium emojis direct paste kar de.</p></div>
<form method="POST">
{{form_fields}}
<button type="submit">💾 SAVE ALL</button>
</form>
</body></html>
"""

def get_buttons():
    c = load_config()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(c["BTN_FILE2LINK"], callback_data="file2link")],
        [InlineKeyboardButton(c["BTN_RENAMER"], callback_data="renamer")],
        [InlineKeyboardButton(c["BTN_DOWNLOADER"], callback_data="downloader")]
    ])

@flask_app.route("/")
def home(): return "Tagda Bot Alive!"

@flask_app.route("/watch/<path:filename>")
def watch(filename):
    return send_from_directory("downloads", filename, as_attachment=False)

@flask_app.route("/admin", methods=["GET","POST"])
def admin_panel():
    c = load_config()
    if request.method == "POST":
        for k in c.keys():
            if k in request.form:
                c[k] = request.form[k]
        save_config(c)
        return redirect("/admin")
    fields = ""
    for k,v in c.items():
        if len(v) > 50:
            fields += f'<label>{k}</label><textarea name="{k}" rows="3">{v}</textarea>'
        else:
            fields += f'<label>{k}</label><input name="{k}" value="{v}">'
    html = ADMIN_HTML.replace("{{base_url}}", BASE_URL).replace("{{form_fields}}", fields)
    return html

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = load_config()
    await update.message.reply_text(c["START_MSG"], reply_markup=get_buttons(), disable_web_page_preview=True)

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_url = f"{BASE_URL}/admin"
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔥 Admin Panel Kholo", url=admin_url)]])
    await update.message.reply_text(f"Le beo tera admin panel 👇\n\n{admin_url}", reply_markup=btn)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = load_config()
    uid = q.from_user.id
    if q.data == "file2link":
        user_state[uid] = "file2link"
        await q.message.reply_text("File/Video bhejo, main direct link bana dunga.")
    elif q.data == "renamer":
        user_state[uid] = {"mode":"renamer", "step":"wait_file"}
        await q.message.reply_text(c["RENAMER_MSG"])
    elif q.data == "downloader":
        user_state[uid] = "downloader"
        await q.message.reply_text(c["DOWNLOADER_MSG"])

async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = msg.from_user.id
    state = user_state.get(uid)
    c = load_config()
    file_obj = None
    if msg.document: file_obj = msg.document
    elif msg.video: file_obj = msg.video
    elif msg.audio: file_obj = msg.audio
    elif msg.photo: file_obj = msg.photo[-1]
    if not file_obj: return

    if isinstance(state, dict) and state.get("step") == "wait_thumb":
        thumb_file = await context.bot.get_file(file_obj.file_id)
        thumb_path = f"downloads/thumb_{uid}.jpg"
        await thumb_file.download_to_drive(thumb_path)
        orig_path = state["orig_path"]
        new_name = state["new_name"]
        with Image.open(thumb_path) as im:
            w, h = im.size
        output_path = f"downloads/{new_name}"
        try:
            cmd = f'ffmpeg -y -i "{orig_path}" -i "{thumb_path}" -map 0:v:0 -map 0:a? -map 1 -c:v libx264 -vf scale={w}:{h} -c:a copy -c:v:1 mjpeg -disposition:v:1 attached_pic "{output_path}"'
            subprocess.run(cmd, shell=True, timeout=120)
            if not os.path.exists(output_path): raise Exception("fail")
        except:
            if os.path.exists(output_path): os.remove(output_path)
            os.rename(orig_path, output_path)
        else:
            if os.path.exists(orig_path): os.remove(orig_path)
        await msg.reply_document(document=open(output_path, 'rb'), thumbnail=open(thumb_path, 'rb'), filename=new_name, caption=f"Ho gaya beo ✅ {new_name}")
        user_state.pop(uid, None)
        return

    tg_file = await context.bot.get_file(file_obj.file_id)
    orig_name = getattr(file_obj, 'file_name', f"file_{file_obj.file_id}.jpg" if msg.photo else f"file_{file_obj.file_id}")
    temp_path = f"downloads/{orig_name}"
    await tg_file.download_to_drive(temp_path)

    if isinstance(state, dict) and state.get("mode") == "renamer" and state["step"] == "wait_file":
        user_state[uid] = {"mode":"renamer", "step":"wait_name", "orig_path": temp_path}
        await msg.reply_text(c["RENAMER_ASK_NAME_MSG"])
        return

    fname = os.path.basename(temp_path)
    link = f"{BASE_URL}/watch/{fname}"
    await msg.reply_text(f"{c['FILE2LINK_MSG']}\n\n{link}", reply_markup=get_buttons())
    user_state.pop(uid, None)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = msg.from_user.id
    state = user_state.get(uid)
    text = msg.text.strip()
    c = load_config()
    if isinstance(state, dict) and state.get("mode") == "renamer" and state["step"] == "wait_name":
        state["new_name"] = text
        state["step"] = "wait_thumb"
        user_state[uid] = state
        await msg.reply_text(c["THUMBNAIL_MSG"])
        return
    if text.startswith("http"):
        await msg.reply_text("Downloading... ⏳")
        try:
            ydl_opts = {'outtmpl': 'downloads/%(title)s.%(ext)s', 'format': 'best'}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                file_path = ydl.prepare_filename(info)
            await msg.reply_document(document=open(file_path, 'rb'), caption=f"Downloaded: {info.get('title')}")
        except Exception as e:
            await msg.reply_text(f"Error: {e}")
        user_state.pop(uid, None)

async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    state = user_state.get(uid)
    if isinstance(state, dict) and state.get("step") == "wait_thumb":
        orig_path = state["orig_path"]
        new_name = state["new_name"]
        output_path = f"downloads/{new_name}"
        os.rename(orig_path, output_path)
        await update.message.reply_document(document=open(output_path, 'rb'), filename=new_name, caption=f"Renamed to {new_name}")
        user_state.pop(uid, None)

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"Bot Started on {BASE_URL}")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("tradevyx_adarsh_bot", admin_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ATTACHMENT, file_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling()
