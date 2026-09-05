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

// ---------------- DEFAULTS ----------------
const DEFAULT_SETTINGS = {
  brandName: "TRADEVYX",
  welcomeMessage:
    "👋 Welcome to *TRADEVYX*!\n\nTrading, Options, Forex & Crypto courses seedhe yahin se.",
  helpMessage:
    "*Available Commands*\n\n/courses - Sab courses ki list\n/course <id> - Ek course ki detail\n/contact - Admin se baat karo",
  footerText: "_TRADEVYX — Trade Smart, Trade Safe_",
  contactUsername: "@your_username_here",
  buttons: {
    courses: "📚 Courses",
    help: "ℹ️ Help",
    contact: "💬 Contact",
  },
};

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

// send a message that may contain emoji placeholders (no Markdown mixed in)
function sendRich(chatId, rawText, extraOptions = {}) {
  const { text, entities } = renderWithEmojis(rawText);
  const options = { ...extraOptions };
  if (entities.length > 0) {
    options.entities = entities;
  } else {
    options.parse_mode = "Markdown";
  }
  return bot.sendMessage(chatId, text, options);
}

// ================================================================
// USER-FACING COMMANDS
// ================================================================

bot.onText(/\/start/, (msg) => {
  const chatId = msg.chat.id;
  trackUser(msg.from.id);
  const settings = getSettings();
  sendRich(chatId, settings.welcomeMessage, {
    reply_markup: {
      inline_keyboard: [
        [{ text: settings.buttons.courses, callback_data: "menu_courses" }],
        [
          { text: settings.buttons.help, callback_data: "menu_help" },
          { text: settings.buttons.contact, callback_data: "menu_contact" },
        ],
      ],
    },
  });
});

bot.onText(/\/help/, (msg) => {
  const settings = getSettings();
  sendRich(msg.chat.id, settings.helpMessage);
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
      return `${i + 1}. *${c.title}*\n   💰 ₹${c.price}\n   🆔 \`${key}\``;
    })
    .join("\n\n");
}

bot.onText(/\/courses/, (msg) => {
  const courses = getCourses();
  const settings = getSettings();
  bot.sendMessage(
    msg.chat.id,
    `📚 *Available Courses*\n\n${courseListText(courses)}\n\nDetail ke liye: \`/course <id>\`\n\n${settings.footerText}`,
    { parse_mode: "Markdown" }
  );
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
  bot.sendMessage(
    msg.chat.id,
    `📖 *${c.title}*\n\n${c.description || "No description"}\n\n💰 Price: ₹${c.price}\n\n_Payment ke liye admin se contact karo: /contact_`,
    { parse_mode: "Markdown" }
  );
});

// inline button clicks
bot.on("callback_query", async (query) => {
  const chatId = query.message.chat.id;
  if (query.data === "menu_courses") {
    const courses = getCourses();
    bot.sendMessage(chatId, `📚 *Available Courses*\n\n${courseListText(courses)}`, {
      parse_mode: "Markdown",
    });
  } else if (query.data === "menu_help") {
    sendRich(chatId, getSettings().helpMessage);
  } else if (query.data === "menu_contact") {
    bot.sendMessage(chatId, `💬 Admin se contact karo: ${getSettings().contactUsername}`);
  }
  bot.answerCallbackQuery(query.id);
});

// ================================================================
// ADMIN PANEL
// ================================================================

bot.onText(/\/admin$/, (msg) => {
  if (!isAdmin(msg.from.id)) return bot.sendMessage(msg.chat.id, "⛔ Ye command sirf admin ke liye hai.");
  bot.sendMessage(
    msg.chat.id,
    `🛠 *TRADEVYX Admin Panel*\n\n` +
      `*📚 Courses*\n/addcourse - naya course\n/editcourse <id>\n/delcourse <id>\n/listcourses\n\n` +
      `*✏️ Editable Texts*\n/setwelcome - welcome message\n/sethelp - help message\n/setfooter - footer text\n/setbrand - brand name\n/setcontact - contact username\n/setbutton <key> <text> - courses/help/contact\n\n` +
      `*😎 Premium Emojis*\n/addemoji <keyword> - phir wo emoji bhejo\n/listemojis\n/delemoji <keyword>\n\n` +
      `*📢 Other*\n/broadcast - sabko message bhejo\n/stats - bot stats`,
    { parse_mode: "Markdown" }
  );
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
  bot.sendMessage(msg.chat.id, courseListText(getCourses()), { parse_mode: "Markdown" });
});

// ---------------- EDITABLE TEXTS ----------------

bot.onText(/\/setwelcome/, (msg) => {
  if (!isAdmin(msg.from.id)) return;
  adminState[msg.from.id] = { flow: "setWelcome" };
  bot.sendMessage(
    msg.chat.id,
    "✏️ Naya *welcome message* bhejo.\n\n_Tip: premium emoji use karne ke liye_ `:keyword:` _likho, e.g._ `Welcome :fire: to TRADEVYX`",
    { parse_mode: "Markdown" }
  );
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

bot.onText(/\/setbutton (\w+) (.+)/, (msg, match) => {
  if (!isAdmin(msg.from.id)) return;
  const key = match[1].trim();
  const text = match[2].trim();
  const settings = getSettings();
  if (!["courses", "help", "contact"].includes(key)) {
    return bot.sendMessage(msg.chat.id, "⚠️ Key must be: courses, help, ya contact");
  }
  settings.buttons[key] = text;
  saveSettings(settings);
  bot.sendMessage(msg.chat.id, `✅ Button "${key}" update ho gaya: ${text}`);
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
  bot.sendMessage(
    msg.chat.id,
    `📊 *TRADEVYX Bot Stats*\n\n👥 Users: ${users.length}\n📚 Courses: ${Object.keys(courses).length}\n😎 Custom Emojis: ${Object.keys(emojis).length}`,
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
    settings.welcomeMessage = msg.text;
    saveSettings(settings);
    bot.sendMessage(msg.chat.id, "✅ Welcome message update ho gaya! Preview:");
    sendRich(msg.chat.id, settings.welcomeMessage);
    delete adminState[userId];
    return;
  }
  if (state.flow === "setHelp") {
    const settings = getSettings();
    settings.helpMessage = msg.text;
    saveSettings(settings);
    bot.sendMessage(msg.chat.id, "✅ Help message update ho gaya! Preview:");
    sendRich(msg.chat.id, settings.helpMessage);
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
    let sent = 0;
    for (const uid of users) {
      try {
        await sendRich(uid, msg.text);
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
