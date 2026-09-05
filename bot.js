// ================================================================
// TRADEVYX Course Bot — FULL POWER EDITION
// Everything editable from inside Telegram + Premium Custom Emoji
// No Firebase, no external DB — simple JSON file storage
// ================================================================

const TelegramBot = require("node-telegram-bot-api");
const fs = require("fs");
const path = require("path");
require("dotenv").config();

// ---------------- CONFIG ----------------
const BOT_TOKEN = process.env.BOT_TOKEN;
const ADMIN_IDS = (process.env.ADMIN_IDS || "").split(",").map((id) => id.trim());

// ---------------- FILE PATHS ----------------
const SETTINGS_FILE = path.join(__dirname, "settings.json");
const COURSES_FILE = path.join(__dirname, "courses.json");
const EMOJIS_FILE = path.join(__dirname, "emojis.json");
const USERS_FILE = path.join(__dirname, "users.json");
const BUTTONS_FILE = path.join(__dirname, "buttons.json");

// ---------------- DEFAULTS ----------------
const DEFAULT_SETTINGS = {
  brandName: "TRADEVYX",
  welcomeMessage:
    "👋 Welcome to *TRADEVYX*!\n\nTrading, Options, Forex & Crypto courses seedhe yahin se.",
  welcomeEntities: [], // exact formatting/premium-emoji entities from admin's message, if any
  welcomeImage: null, // Telegram file_id of the welcome image, if set
  helpMessage:
    "*Available Commands*\n\n/courses - Sab courses ki list\n/course <id> - Ek course ki detail\n/contact - Admin se baat karo",
  helpEntities: [],
  footerText: "_TRADEVYX — Trade Smart, Trade Safe_",
  contactUsername: "@your_username_here",
};

// Default menu buttons shown under /start — fully editable, any number, any order
const DEFAULT_BUTTONS = [
  { id: "btn_courses", text: "📚 Courses", type: "courses_list", value: null },
  { id: "btn_help", text: "ℹ️ Help", type: "help", value: null },
  { id: "btn_contact", text: "💬 Contact", type: "contact", value: null },
];

// ---------------- STORAGE HELPERS ----------------
function readJSON(file, fallback) {
  if (!fs.existsSync(file)) return fallback;
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch (e) {
    return fallback;
  }
}
function writeJSON(file, data) {
  fs.writeFileSync(file, JSON.stringify(data, null, 2));
}

function getSettings() {
  return { ...DEFAULT_SETTINGS, ...readJSON(SETTINGS_FILE, {}) };
}
function saveSettings(settings) {
  writeJSON(SETTINGS_FILE, settings);
}
function getCourses() {
  return readJSON(COURSES_FILE, {});
}
function saveCourses(courses) {
  writeJSON(COURSES_FILE, courses);
}
function getEmojis() {
  return readJSON(EMOJIS_FILE, {});
}
function saveEmojis(emojis) {
  writeJSON(EMOJIS_FILE, emojis);
}
function getUsers() {
  return readJSON(USERS_FILE, []);
}
function saveUsers(users) {
  writeJSON(USERS_FILE, users);
}
function getButtons() {
  return readJSON(BUTTONS_FILE, DEFAULT_BUTTONS);
}
function saveButtons(buttons) {
  writeJSON(BUTTONS_FILE, buttons);
}
function buildKeyboard(buttons) {
  const rows = [];
  for (let i = 0; i < buttons.length; i += 2) {
    const row = buttons.slice(i, i + 2).map((b) => {
      if (b.type === "url") return { text: b.text, url: b.value };
      return { text: b.text, callback_data: `custom_btn_${b.id}` };
    });
    rows.push(row);
  }
  return rows;
}
function trackUser(userId) {
  const users = getUsers();
  if (!users.includes(userId)) {
    users.push(userId);
    saveUsers(users);
  }
}

// ---------------- BOT INIT ----------------
const bot = new TelegramBot(BOT_TOKEN, { polling: true });

// ---------------- ADMIN CHECK ----------------
function isAdmin(userId) {
  return ADMIN_IDS.includes(String(userId));
}

// in-memory multi-step flow state per admin user
const adminState = {}; // { userId: { flow, step, data } }

// ================================================================
// PREMIUM CUSTOM EMOJI ENGINE
// Admin-editable texts can contain :keyword: placeholders.
// e.g. "Welcome :fire: to TRADEVYX :rocket:"
// These get replaced with the real premium emoji + custom_emoji entity.
// ================================================================
function renderWithEmojis(rawText) {
  const emojis = getEmojis();
  const regex = /:([a-zA-Z0-9_]+):/g;
  let resultText = "";
  let entities = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(rawText)) !== null) {
    const keyword = match[1];
    const emoji = emojis[keyword];
    resultText += rawText.slice(lastIndex, match.index);

    if (emoji) {
      const offset = resultText.length; // UTF-16 code units, matches Telegram's requirement
      resultText += emoji.char;
      entities.push({
        type: "custom_emoji",
        offset,
        length: emoji.char.length,
        custom_emoji_id: emoji.custom_emoji_id,
      });
    } else {
      resultText += match[0]; // unknown keyword, keep literal text
    }
    lastIndex = regex.lastIndex;
  }
  resultText += rawText.slice(lastIndex);
  return { text: resultText, entities };
}

// Telegram silently drops "complex" entities (blockquote, custom_emoji, text_link, ...)
// if they carry unexpected extra fields or aren't ordered the way it expects
// (outer/longer entities before nested ones, offset ascending). node-telegram-bot-api
// just forwards msg.entities/caption_entities as-is, and those objects can include
// extra properties depending on Telegram client version — so we rebuild each entity
// with only the fields that type actually needs, and sort them safely, before ever
// storing or resending them. This is what was causing quote-boxes and premium emoji
// to disappear while bold/underline (simple entities) kept working.
function sanitizeEntities(entities) {
  if (!Array.isArray(entities) || entities.length === 0) return [];
  const cleaned = entities.map((e) => {
    const base = { type: e.type, offset: e.offset, length: e.length };
    switch (e.type) {
      case "custom_emoji":
        base.custom_emoji_id = e.custom_emoji_id;
        break;
      case "text_link":
        base.url = e.url;
        break;
      case "text_mention":
        base.user = e.user;
        break;
      case "pre":
        if (e.language) base.language = e.language;
        break;
    }
    return base;
  });
  // Telegram expects entities sorted by offset ascending; when two entities start
  // at the same offset, the outer/longer one must come first so nested ones
  // (e.g. a custom_emoji inside a blockquote) aren't treated as invalid overlaps.
  cleaned.sort((a, b) => a.offset - b.offset || b.length - a.length);
  return cleaned;
}

// Extracts the exact text + formatting (bold, quote blocks, premium emoji, etc.)
// from a message the admin sent, so we can replay it byte-for-byte to users
// instead of losing all styling. Works for both text messages and photo captions.
function extractRichContent(msg) {
  if (msg.photo && msg.photo.length > 0) {
    return {
      isPhoto: true,
      fileId: msg.photo[msg.photo.length - 1].file_id,
      text: msg.caption || "",
      entities: sanitizeEntities(msg.caption_entities || []),
    };
  }
  return {
    isPhoto: false,
    fileId: null,
    text: msg.text || "",
    entities: sanitizeEntities(msg.entities || []),
  };
}
// send a message. If rawEntities is provided (from an admin's original formatted
// message), replay it exactly — preserves premium emoji, bold, quote-blocks, etc.
// Otherwise fall back to :keyword: emoji placeholders + Markdown for plain typed text.
function sendRich(chatId, rawText, extraOptions = {}, rawEntities = null) {
  const options = { ...extraOptions };
  if (rawEntities && rawEntities.length > 0) {
    options.entities = sanitizeEntities(rawEntities);
    return bot.sendMessage(chatId, rawText, options).catch((e) => {
      console.error("sendRich (entities) failed:", e.response ? e.response.body : e.message);
    });
  }
  const { text, entities } = renderWithEmojis(rawText);
  if (entities.length > 0) {
    options.entities = entities;
  } else {
    options.parse_mode = "Markdown";
  }
  return bot.sendMessage(chatId, text, options).catch((e) => {
    console.error("sendRich (fallback) failed:", e.response ? e.response.body : e.message);
  });
}

// same idea but for a photo caption
function sendRichPhoto(chatId, fileId, rawCaption, extraOptions = {}, rawEntities = null) {
  const options = { ...extraOptions, caption: rawCaption || "" };
  if (rawEntities && rawEntities.length > 0) {
    options.caption_entities = sanitizeEntities(rawEntities);
    return bot.sendPhoto(chatId, fileId, options).catch((e) => {
      console.error("sendRichPhoto (entities) failed:", e.response ? e.response.body : e.message);
    });
  }
  const { text, entities } = renderWithEmojis(rawCaption || "");
  options.caption = text;
  if (entities.length > 0) {
    options.caption_entities = entities;
  } else {
    options.parse_mode = "Markdown";
  }
  return bot.sendPhoto(chatId, fileId, options).catch((e) => {
    console.error("sendRichPhoto (fallback) failed:", e.response ? e.response.body : e.message);
  });
}

// sends the welcome message, with image if one is set — replays exact formatting if saved
function sendWelcome(chatId, settings, extraOptions = {}) {
  if (settings.welcomeImage) {
    return sendRichPhoto(chatId, settings.welcomeImage, settings.welcomeMessage, extraOptions, settings.welcomeEntities);
  }
  return sendRich(chatId, settings.welcomeMessage, extraOptions, settings.welcomeEntities);
}

// ================================================================
// USER-FACING COMMANDS
// ================================================================

bot.onText(/\/start/, (msg) => {
  const chatId = msg.chat.id;
  trackUser(msg.from.id);
  const settings = getSettings();
  const buttons = getButtons();
  sendWelcome(chatId, settings, {
    reply_markup: { inline_keyboard: buildKeyboard(buttons) },
  });
});

bot.onText(/\/help/, (msg) => {
  const settings = getSettings();
  sendRich(msg.chat.id, settings.helpMessage, {}, settings.helpEntities);
});

bot.onText(/\/contact/, (msg) => {
  const settings = getSettings();
  bot.sendMessage(msg.chat.id, `💬 Admin se contact karo: ${settings.contactUsername}`);
});

function courseListText(courses) {
  const keys = Object.keys(courses);
  if (keys.length === 0) return "Abhi koi course add nahi hua hai.";
  return keys
    .map((key, i) => {
      const c = courses[key];
      return `${i + 1}. *${c.title}*\n   💰 ₹${c.price}`;
    })
    .join("\n\n");
}

// builds a button for every course so users never need to type /course <id>
function courseListKeyboard(courses) {
  const keys = Object.keys(courses);
  const rows = keys.map((key) => [{ text: `📖 ${courses[key].title}`, callback_data: `view_course_${key}` }]);
  rows.push([{ text: "🏠 Menu", callback_data: "back_to_menu" }]);
  return rows;
}

function courseDetailText(c) {
  return `📖 *${c.title}*\n\n${c.description || "No description"}\n\n💰 Price: ₹${c.price}\n\n_Payment ke liye niche Contact button dabao._`;
}

// admin needs to see IDs to run /editcourse, /delcourse, /addbutton etc.
function adminCourseListText(courses) {
  const keys = Object.keys(courses);
  if (keys.length === 0) return "Abhi koi course add nahi hua hai.";
  return keys
    .map((key, i) => {
      const c = courses[key];
      return `${i + 1}. *${c.title}*\n   💰 ₹${c.price}\n   🆔 \`${key}\``;
    })
    .join("\n\n");
}

bot.onText(/\/courses/, (msg) => {
  const courses = getCourses();
  bot.sendMessage(msg.chat.id, `📚 *Available Courses*\n\nNiche tap karo dekhne ke liye:`, {
    parse_mode: "Markdown",
    reply_markup: { inline_keyboard: courseListKeyboard(courses) },
  });
});

bot.onText(/\/course (.+)/, (msg, match) => {
  const id = match[1].trim();
  const courses = getCourses();
  const c = courses[id];
  if (!c) {
    return bot.sendMessage(msg.chat.id, "❌ Ye course id nahi mili. `/courses` se list dekho.", {
      parse_mode: "Markdown",
    });
  }
  bot.sendMessage(msg.chat.id, courseDetailText(c), { parse_mode: "Markdown" });
});

// inline button clicks
bot.on("callback_query", async (query) => {
  const chatId = query.message.chat.id;
  const data = query.data;
  bot.answerCallbackQuery(query.id);

  if (data === "back_to_menu") {
    const settings = getSettings();
    const buttons = getButtons();
    return sendWelcome(chatId, settings, { reply_markup: { inline_keyboard: buildKeyboard(buttons) } });
  }

  if (data.startsWith("view_course_")) {
    const id = data.replace("view_course_", "");
    const courses = getCourses();
    const c = courses[id];
    if (!c) return bot.sendMessage(chatId, "❌ Ye course ab available nahi hai.");
    return bot.sendMessage(chatId, courseDetailText(c), {
      parse_mode: "Markdown",
      reply_markup: { inline_keyboard: [[{ text: "⬅️ Sab Courses", callback_data: "action_courses_list" }]] },
    });
  }

  if (data === "action_courses_list") {
    const courses = getCourses();
    return bot.sendMessage(chatId, `📚 *Available Courses*\n\nNiche tap karo dekhne ke liye:`, {
      parse_mode: "Markdown",
      reply_markup: { inline_keyboard: courseListKeyboard(courses) },
    });
  }

  if (data.startsWith("custom_btn_")) {
    const id = data.replace("custom_btn_", "");
    const buttons = getButtons();
    const btn = buttons.find((b) => b.id === id);
    if (!btn) return;

    if (btn.type === "courses_list") {
      const courses = getCourses();
      bot.sendMessage(chatId, `📚 *Available Courses*\n\nNiche tap karo dekhne ke liye:`, {
        parse_mode: "Markdown",
        reply_markup: { inline_keyboard: courseListKeyboard(courses) },
      });
    } else if (btn.type === "help") {
      { const s = getSettings(); sendRich(chatId, s.helpMessage, {}, s.helpEntities); }
    } else if (btn.type === "contact") {
      bot.sendMessage(chatId, `💬 Admin se contact karo: ${getSettings().contactUsername}`);
    } else if (btn.type === "course") {
      const courses = getCourses();
      const c = courses[btn.value];
      if (!c) return bot.sendMessage(chatId, "❌ Ye course ab available nahi hai.");
      bot.sendMessage(chatId, courseDetailText(c), { parse_mode: "Markdown" });
    } else if (btn.type === "text") {
      sendRich(chatId, btn.value || "", {}, btn.valueEntities);
    }
  }
});

// ================================================================
// ADMIN PANEL
// ================================================================

bot.onText(/\/admin$/, (msg) => {
  if (!isAdmin(msg.from.id)) return bot.sendMessage(msg.chat.id, "⛔ Ye command sirf admin ke liye hai.");

  const part1 =
    `🛠 *TRADEVYX Admin Panel — Poori Guide*\n\n` +
    `━━━━━━━━━━━━━━\n📚 *COURSES*\n━━━━━━━━━━━━━━\n\n` +
    `\`/addcourse\`\nNaya course add karo. Bot 3 sawal poochega: title → description → price. Bas jawab likhte jao.\n\n` +
    `\`/editcourse <id>\`\nExisting course update karo (same 3 steps dubara).\nExample: \`/editcourse course_123\`\n\n` +
    `\`/delcourse <id>\`\nCourse delete karo.\nExample: \`/delcourse course_123\`\n\n` +
    `\`/listcourses\`\nSab courses dikhao unki ID ke saath (ID chahiye edit/delete karne ke liye).`;

  const part2 =
    `━━━━━━━━━━━━━━\n✏️ *BOT KE MESSAGES*\n━━━━━━━━━━━━━━\n\n` +
    `\`/setwelcome\`\n/start pe jo pehla message dikhta hai wo badlo. Sirf *text* bhejo, ya *image bhejo caption ke saath* (photo + caption text hi welcome message ban jayega).\n_Tip: agar tum koi already design kiya hua message (bold/quote-box/premium emoji wala) forward ya copy-paste karke bhejoge, bot uski poori formatting hubahu copy kar lega._\n\n` +
    `\`/removewelcomeimage\`\nWelcome image hatao, sirf text wapas dikhega.\n\n` +
    `\`/sethelp\`\n/help command ka reply text badlo.\n\n` +
    `\`/setfooter\`\n/courses list ke neeche chhota text badlo.\n\n` +
    `\`/setbrand\`\nBot ka brand naam badlo (abhi TRADEVYX hai).\n\n` +
    `\`/setcontact\`\n/contact pe jo username dikhta hai wo badlo.\nExample bhejna: \`@tradevyx_support\``;

  const part3 =
    `━━━━━━━━━━━━━━\n🔘 *BUTTONS (jitne chaho utne)*\n━━━━━━━━━━━━━━\n\n` +
    `_Note: Telegram button ka color/design change nahi hota — ye Telegram khud control karta hai. Lekin text, count, order aur kya khulega (course/link/message) — sab tum control karte ho._\n\n` +
    `\`/addbutton\`\nNaya button add karo. Bot poochega: text → type (course/courses_list/help/contact/text/url) → agar zarurat ho to value (jaise course ID ya link).\n\n` +
    `\`/editbutton <id>\`\nExisting button update karo.\n\n` +
    `\`/delbutton <id>\`\nButton hatao.\n\n` +
    `\`/listbuttons\`\nSab buttons dekho unki ID, type, value ke saath.\n\n` +
    `\`/movebutton <id> up\` ya \`/movebutton <id> down\`\nButton ka order badlo (upar/neeche).`;

  const part4 =
    `━━━━━━━━━━━━━━\n😎 *PREMIUM EMOJI*\n━━━━━━━━━━━━━━\n(Sirf Telegram Premium walon ke liye)\n\n` +
    `\`/addemoji <keyword>\`\nBot poochega emoji bhejo — wahi premium emoji bhej do (extra text nahi).\nExample: \`/addemoji fire\` phir wo emoji bhejo.\n\n` +
    `\`/listemojis\`\nSaari saved emoji dekho.\n\n` +
    `\`/delemoji <keyword>\`\nEmoji hatao.\n\n` +
    `Fir kisi bhi editable text mein \`:fire:\` likhoge to wahi premium emoji aayegi.`;

  const part5 =
    `━━━━━━━━━━━━━━\n📢 *BAAKI SAB*\n━━━━━━━━━━━━━━\n\n` +
    `\`/broadcast\`\nJo bhi message likhoge, wo turant *sab users* ko chala jayega. Emoji bhi kaam karenge.\n\n` +
    `\`/stats\`\nKitne users hain, kitne courses hain, kitni emoji hain — sab dikhega.\n\n` +
    `\`/admin\`\nYe poori list dobara dikhne ke liye.`;

  bot.sendMessage(msg.chat.id, part1, { parse_mode: "Markdown" });
  bot.sendMessage(msg.chat.id, part2, { parse_mode: "Markdown" });
  bot.sendMessage(msg.chat.id, part3, { parse_mode: "Markdown" });
  bot.sendMessage(msg.chat.id, part4, { parse_mode: "Markdown" });
  bot.sendMessage(msg.chat.id, part5, { parse_mode: "Markdown" });
});

// ---------------- COURSES: ADD / EDIT / DELETE / LIST ----------------

bot.onText(/\/addcourse/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "course", step: "title", data: {} };
  bot.sendMessage(msg.chat.id, "➕ *Naya Course*\n\nCourse ka *title* bhejo:", { parse_mode: "Markdown" });
});

bot.onText(/\/editcourse (.+)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const id = match[1].trim();
  const courses = getCourses();
  if (!courses[id]) return bot.sendMessage(msg.chat.id, "❌ Ye id nahi mili.");
  adminState[msg.from.id] = { flow: "course", step: "title", data: {}, editId: id };
  bot.sendMessage(msg.chat.id, `✏️ Editing \`${id}\`\n\nNaya *title* bhejo:`, { parse_mode: "Markdown" });
});

bot.onText(/\/delcourse (.+)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const id = match[1].trim();
  const courses = getCourses();
  delete courses[id];
  saveCourses(courses);
  bot.sendMessage(msg.chat.id, `🗑 Course \`${id}\` delete ho gaya.`, { parse_mode: "Markdown" });
});

bot.onText(/\/listcourses/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  bot.sendMessage(msg.chat.id, adminCourseListText(getCourses()), { parse_mode: "Markdown" });
});

// ---------------- EDITABLE TEXTS ----------------

bot.onText(/\/setwelcome/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "setWelcome" };
  bot.sendMessage(
    msg.chat.id,
    "✏️ Naya *welcome message* bhejo.\n\n" +
      "👉 Sirf *text* bhejo agar bina image ke chahiye.\n" +
      "👉 Ya *image bhejo caption ke saath* — wahi caption welcome message ban jayega, image bhi lag jayegi.\n\n" +
      "_Tip: premium emoji use karne ke liye_ `:keyword:` _likho, e.g._ `Welcome :fire: to TRADEVYX`",
    { parse_mode: "Markdown" }
  );
});

bot.onText(/\/removewelcomeimage/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  const settings = getSettings();
  settings.welcomeImage = null;
  saveSettings(settings);
  bot.sendMessage(msg.chat.id, "✅ Welcome image hata di gayi, ab sirf text dikhega.");
});

bot.onText(/\/sethelp/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "setHelp" };
  bot.sendMessage(msg.chat.id, "✏️ Naya *help message* bhejo:", { parse_mode: "Markdown" });
});

bot.onText(/\/setfooter/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "setFooter" };
  bot.sendMessage(msg.chat.id, "✏️ Naya *footer text* bhejo:", { parse_mode: "Markdown" });
});

bot.onText(/\/setbrand/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "setBrand" };
  bot.sendMessage(msg.chat.id, "✏️ Naya *brand name* bhejo:", { parse_mode: "Markdown" });
});

bot.onText(/\/setcontact/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "setContact" };
  bot.sendMessage(msg.chat.id, "✏️ Naya *contact username* bhejo (e.g. @tradevyx_support):", {
    parse_mode: "Markdown",
  });
});

// ---------------- DYNAMIC BUTTONS ----------------

bot.onText(/\/addbutton/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "button", step: "text", data: {} };
  bot.sendMessage(msg.chat.id, "🔘 *Naya Button*\n\nButton ka *text/naam* bhejo (jo dikhega):", {
    parse_mode: "Markdown",
  });
});

bot.onText(/\/editbutton (\S+)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const id = match[1].trim();
  const buttons = getButtons();
  if (!buttons.find((b) => b.id === id)) return bot.sendMessage(msg.chat.id, "❌ Ye button id nahi mili.");
  adminState[msg.from.id] = { flow: "button", step: "text", data: {}, editId: id };
  bot.sendMessage(msg.chat.id, `✏️ Editing \`${id}\`\n\nNaya *text/naam* bhejo:`, { parse_mode: "Markdown" });
});

bot.onText(/\/delbutton (\S+)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const id = match[1].trim();
  let buttons = getButtons();
  buttons = buttons.filter((b) => b.id !== id);
  saveButtons(buttons);
  bot.sendMessage(msg.chat.id, `🗑 Button \`${id}\` delete ho gaya.`, { parse_mode: "Markdown" });
});

bot.onText(/\/listbuttons/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  const buttons = getButtons();
  if (buttons.length === 0) return bot.sendMessage(msg.chat.id, "Koi button nahi hai abhi.");
  const text = buttons
    .map(
      (b, i) =>
        `${i + 1}. *${b.text}*\n   🆔 \`${b.id}\`\n   Type: ${b.type}${b.value ? `\n   Value: ${b.value}` : ""}`
    )
    .join("\n\n");
  bot.sendMessage(msg.chat.id, `🔘 *Menu Buttons* (order same as displayed, 2 per row)\n\n${text}`, {
    parse_mode: "Markdown",
  });
});

bot.onText(/\/movebutton (\S+) (up|down)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const id = match[1].trim();
  const dir = match[2].trim();
  const buttons = getButtons();
  const idx = buttons.findIndex((b) => b.id === id);
  if (idx === -1) return bot.sendMessage(msg.chat.id, "❌ Ye button id nahi mili.");
  const swapWith = dir === "up" ? idx - 1 : idx + 1;
  if (swapWith < 0 || swapWith >= buttons.length) return bot.sendMessage(msg.chat.id, "⚠️ Already end/start pe hai.");
  [buttons[idx], buttons[swapWith]] = [buttons[swapWith], buttons[idx]];
  saveButtons(buttons);
  bot.sendMessage(msg.chat.id, `✅ Button order update ho gaya.`);
});

// ---------------- PREMIUM CUSTOM EMOJIS ----------------

bot.onText(/\/addemoji (\w+)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const keyword = match[1].trim();
  adminState[msg.from.id] = { flow: "addEmoji", keyword };
  bot.sendMessage(
    msg.chat.id,
    `😎 Ab wo *premium emoji* bhejo jo keyword \`${keyword}\` se link karna hai.\n\n_(Tumhare paas Telegram Premium hona chahiye taaki emoji "custom emoji" ke roop mein bheji jaaye)_`,
    { parse_mode: "Markdown" }
  );
});

bot.onText(/\/listemojis/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  const emojis = getEmojis();
  const keys = Object.keys(emojis);
  if (keys.length === 0) return bot.sendMessage(msg.chat.id, "Koi emoji add nahi hui abhi.");
  // send with actual entities so admin can see them rendered
  let text = "";
  let entities = [];
  keys.forEach((key) => {
    const line = `:${key}: → `;
    const offset = text.length + line.length;
    text += line + emojis[key].char + "\n";
    entities.push({
      type: "custom_emoji",
      offset,
      length: emojis[key].char.length,
      custom_emoji_id: emojis[key].custom_emoji_id,
    });
  });
  bot.sendMessage(msg.chat.id, text, { entities });
});

bot.onText(/\/delemoji (\w+)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const keyword = match[1].trim();
  const emojis = getEmojis();
  delete emojis[keyword];
  saveEmojis(emojis);
  bot.sendMessage(msg.chat.id, `🗑 Emoji \`${keyword}\` delete ho gaya.`, { parse_mode: "Markdown" });
});

// ---------------- BROADCAST ----------------

bot.onText(/\/broadcast/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "broadcast" };
  bot.sendMessage(
    msg.chat.id,
    "📢 Sabko bhejne wala message likho.\n\n_Premium emoji ke liye_ `:keyword:` _use kar sakte ho._",
    { parse_mode: "Markdown" }
  );
});

// ---------------- STATS ----------------

bot.onText(/\/stats/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  const users = getUsers();
  const courses = getCourses();
  const emojis = getEmojis();
  const buttons = getButtons();
  bot.sendMessage(
    msg.chat.id,
    `📊 *TRADEVYX Bot Stats*\n\n👥 Users: ${users.length}\n📚 Courses: ${Object.keys(courses).length}\n🔘 Buttons: ${buttons.length}\n😎 Custom Emojis: ${Object.keys(emojis).length}`,
    { parse_mode: "Markdown" }
  );
});

// ================================================================
// MULTI-STEP FLOW HANDLER (handles all the /set... and /addcourse etc.)
// ================================================================
bot.on("message", async (msg) => {
  const userId = msg.from.id;
  const state = adminState[userId];
  if (!state || !isAdmin(userId)) return;
  if (msg.text && msg.text.startsWith("/")) return; // don't eat commands

  // ---- Dynamic button creation/edit flow ----
  if (state.flow === "button") {
    if (!msg.text) return;

    if (state.step === "text") {
      state.data.text = msg.text;
      state.step = "type";
      return bot.sendMessage(
        msg.chat.id,
        "🔧 Ab type batao ye button kya karega, in mein se ek word bhejo:\n\n" +
          "`course` — ek specific course dikhayega\n" +
          "`courses_list` — sab courses ki list dikhayega\n" +
          "`help` — help message dikhayega\n" +
          "`contact` — contact info dikhayega\n" +
          "`text` — apna khud ka koi message dikhayega\n" +
          "`url` — kisi link pe le jayega (jaise website/Telegram channel)",
        { parse_mode: "Markdown" }
      );
    }

    if (state.step === "type") {
      const type = msg.text.trim().toLowerCase();
      const validTypes = ["course", "courses_list", "help", "contact", "text", "url"];
      if (!validTypes.includes(type)) {
        return bot.sendMessage(msg.chat.id, "⚠️ Sirf ye types chalenge: course, courses_list, help, contact, text, url");
      }
      state.data.type = type;

      if (type === "courses_list" || type === "help" || type === "contact") {
        // no extra value needed, save directly
        const buttons = getButtons();
        const id = state.editId || `btn_${Date.now()}`;
        const newButton = { id, text: state.data.text, type: state.data.type, value: null };
        const idx = buttons.findIndex((b) => b.id === id);
        if (idx >= 0) buttons[idx] = newButton;
        else buttons.push(newButton);
        saveButtons(buttons);
        bot.sendMessage(msg.chat.id, `✅ Button "${state.data.text}" save ho gaya! 🆔 \`${id}\``, {
          parse_mode: "Markdown",
        });
        delete adminState[userId];
        return;
      }

      state.step = "value";
      if (type === "course") {
        const courses = getCourses();
        return bot.sendMessage(
          msg.chat.id,
          `📚 Course ki ID bhejo (\`/listcourses\` se dekh sakte ho):\n\n${adminCourseListText(courses)}`,
          { parse_mode: "Markdown" }
        );
      }
      if (type === "url") {
        return bot.sendMessage(msg.chat.id, "🔗 Poora link bhejo (https:// ke saath):");
      }
      if (type === "text") {
        return bot.sendMessage(
          msg.chat.id,
          "📝 Ab wo message likho jo button click karne pe dikhna chahiye (`:keyword:` premium emoji ke liye use kar sakte ho):",
          { parse_mode: "Markdown" }
        );
      }
    }

    if (state.step === "value") {
      const rich = extractRichContent(msg);
      state.data.value = rich.text.trim();
      if (state.data.type === "text") {
        state.data.valueEntities = rich.entities;
      }
      const buttons = getButtons();
      const id = state.editId || `btn_${Date.now()}`;
      const newButton = {
        id,
        text: state.data.text,
        type: state.data.type,
        value: state.data.value,
        valueEntities: state.data.valueEntities || [],
      };
      const idx = buttons.findIndex((b) => b.id === id);
      if (idx >= 0) buttons[idx] = newButton;
      else buttons.push(newButton);
      saveButtons(buttons);
      bot.sendMessage(msg.chat.id, `✅ Button "${state.data.text}" save ho gaya! 🆔 \`${id}\``, {
        parse_mode: "Markdown",
      });
      delete adminState[userId];
      return;
    }
    return;
  }

  // ---- Course add/edit flow ----
  if (state.flow === "course") {
    if (state.step === "title") {
      state.data.title = msg.text;
      state.step = "description";
      return bot.sendMessage(msg.chat.id, "📝 Ab *description* bhejo:", { parse_mode: "Markdown" });
    }
    if (state.step === "description") {
      state.data.description = msg.text;
      state.step = "price";
      return bot.sendMessage(msg.chat.id, "💰 Ab *price* bhejo (sirf number, e.g. 999):", {
        parse_mode: "Markdown",
      });
    }
    if (state.step === "price") {
      const price = parseInt(msg.text, 10);
      if (isNaN(price)) return bot.sendMessage(msg.chat.id, "⚠️ Sirf number bhejo, e.g. 999");
      state.data.price = price;

      const id = state.editId || `course_${Date.now()}`;
      const courses = getCourses();
      courses[id] = state.data;
      saveCourses(courses);

      bot.sendMessage(
        msg.chat.id,
        `✅ Course ${state.editId ? "update" : "add"} ho gaya!\n\n🆔 \`${id}\`\n*${state.data.title}*\n💰 ₹${state.data.price}`,
        { parse_mode: "Markdown" }
      );
      delete adminState[userId];
    }
    return;
  }

  // ---- Editable text flows ----
  if (state.flow === "setWelcome") {
    const settings = getSettings();
    const rich = extractRichContent(msg);

    if (rich.isPhoto) {
      settings.welcomeImage = rich.fileId;
      settings.welcomeMessage = rich.text || "👋 Welcome to " + settings.brandName + "!";
      settings.welcomeEntities = rich.entities;
    } else if (rich.text) {
      settings.welcomeImage = null; // plain text welcome, no image
      settings.welcomeMessage = rich.text;
      settings.welcomeEntities = rich.entities;
    } else {
      return bot.sendMessage(msg.chat.id, "⚠️ Text ya image (caption ke saath) bhejo.");
    }

    saveSettings(settings);
    bot.sendMessage(msg.chat.id, "✅ Welcome message update ho gaya! Preview:");
    sendWelcome(msg.chat.id, settings);
    delete adminState[userId];
    return;
  }
  if (state.flow === "setHelp") {
    const settings = getSettings();
    const rich = extractRichContent(msg);
    settings.helpMessage = rich.text;
    settings.helpEntities = rich.entities;
    saveSettings(settings);
    bot.sendMessage(msg.chat.id, "✅ Help message update ho gaya! Preview:");
    sendRich(msg.chat.id, settings.helpMessage, {}, settings.helpEntities);
    delete adminState[userId];
    return;
  }
  if (state.flow === "setFooter") {
    const settings = getSettings();
    settings.footerText = msg.text;
    saveSettings(settings);
    bot.sendMessage(msg.chat.id, "✅ Footer text update ho gaya!");
    delete adminState[userId];
    return;
  }
  if (state.flow === "setBrand") {
    const settings = getSettings();
    settings.brandName = msg.text;
    saveSettings(settings);
    bot.sendMessage(msg.chat.id, `✅ Brand name update ho gaya: ${msg.text}`);
    delete adminState[userId];
    return;
  }
  if (state.flow === "setContact") {
    const settings = getSettings();
    settings.contactUsername = msg.text;
    saveSettings(settings);
    bot.sendMessage(msg.chat.id, `✅ Contact update ho gaya: ${msg.text}`);
    delete adminState[userId];
    return;
  }

  // ---- Add premium emoji flow ----
  if (state.flow === "addEmoji") {
    const entity = (msg.entities || []).find((e) => e.type === "custom_emoji");
    if (!entity) {
      return bot.sendMessage(
        msg.chat.id,
        "⚠️ Ye premium custom emoji nahi mili is message mein. Tumhare paas Telegram Premium hona chahiye, aur seedha wo emoji bhejo (koi extra text nahi)."
      );
    }
    // extract exact characters using UTF-16 slicing (JS strings are UTF-16)
    const char = msg.text.slice(entity.offset, entity.offset + entity.length);
    const emojis = getEmojis();
    emojis[state.keyword] = { custom_emoji_id: entity.custom_emoji_id, char };
    saveEmojis(emojis);
    bot.sendMessage(msg.chat.id, `✅ Emoji save ho gayi! Ab \`:${state.keyword}:\` likhkar kahin bhi use karo.`, {
      parse_mode: "Markdown",
    });
    delete adminState[userId];
    return;
  }

  // ---- Broadcast flow ----
  if (state.flow === "broadcast") {
    const users = getUsers();
    const rich = extractRichContent(msg);
    let sent = 0;
    for (const uid of users) {
      try {
        if (rich.isPhoto) {
          await sendRichPhoto(uid, rich.fileId, rich.text, {}, rich.entities);
        } else {
          await sendRich(uid, rich.text, {}, rich.entities);
        }
        sent++;
      } catch (e) {
        // user may have blocked the bot — skip silently
      }
    }
    bot.sendMessage(msg.chat.id, `📢 Broadcast bhej diya ${sent}/${users.length} users ko.`);
    delete adminState[userId];
    return;
  }
});

console.log("🤖 TRADEVYX Bot (Full Power Edition) is running...");
