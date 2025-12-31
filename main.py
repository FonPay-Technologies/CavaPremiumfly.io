# main.py
import os
import time
import logging
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify
import telegram  # <<< REQUIRED
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, JobQueue
from datetime import timedelta
import time
from telegram import Update, BotCommand
from telegram import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
)

from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ChatMemberHandler  # If you use join detection
)
import re

LINK_REGEX = re.compile(
    r"""
    (
        (https?:\/\/)?                # http or https (optional)
        (www\.)?                      # www (optional)
        [a-zA-Z0-9-]+\.[a-zA-Z]{2,}   # domain.tld
        (\/\S*)?                     # optional path
    )
    """,
    re.IGNORECASE | re.VERBOSE
)

import re
from telegram.error import BadRequest

# -------------------- CONFIG --------------------
# You provided these values
TOKEN = os.environ.get("TOKEN") or "8325305060:AAGYUavCLlErFfGs-CXBiZT5YaMZaEKSCvI"
# Admin IDs (multiple allowed)
ADMIN_IDS = set(int(x.strip()) for x in os.environ.get("ADMIN_IDS", "5236441213,5725566044").split(","))
PREMIUM_APPS_LINK = os.environ.get("PREMIUM_APPS_LINK", "https://t.me/gsf8mqOl0atkMTM0")
CHEAP_DATA_LINK = os.environ.get("CHEAP_DATA_LINK", "https://play.google.com/store/apps/details?id=fonpaybusiness.aowd")
# Monetag zone - set later via env or admin command
MONETAG_ZONE = os.environ.get("MONETAG_ZONE") or "10136395"
MONETAG_LINK = f"https://libtl.com/zone/{MONETAG_ZONE}"
# Grace and inactivity settings
GRACE_SECONDS = int(os.environ.get("GRACE_SECONDS", "60"))          # 1 minute grace after browser close
INACTIVITY_MS = int(os.environ.get("INACTIVITY_MS", str(60*1000)))  # 1 minute inactivity (client)

# Default required ads (you requested 7)
TOTAL_ADS_FILE = "total_ads.txt"
DEFAULT_REQUIRED_ADS = 7

# Files for toggles and links
MODE_FILE = "mode.txt"      # monetag|promo
PROMO_FILE = "promo.txt"
GIFT_FILE = "gift.txt"

# ------------------ OWNERS ------------------

BOT_OWNER_IDS = {5236441213, 5725566044}

def is_bot_owner(user_id):
    return int(user_id) in BOT_OWNER_IDS

# ===== MODERATION TOGGLE =====
MODERATION_ENABLED = {}

# -------------------- LOGGING --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- UTILS: files and dynamic ads --------------------
def get_required_ads():
    try:
        return int(open(TOTAL_ADS_FILE).read().strip())
    except Exception:
        return DEFAULT_REQUIRED_ADS

def set_required_ads(n: int):
    n = int(n)
    with open(TOTAL_ADS_FILE, "w") as f:
        f.write(str(n))

# ensure total_ads file exists with default 7
if not os.path.exists(TOTAL_ADS_FILE):
    set_required_ads(DEFAULT_REQUIRED_ADS)

# ensure supporting files exist
if not os.path.exists(MODE_FILE):
    with open(MODE_FILE, "w") as f:
        f.write("monetag")
if not os.path.exists(PROMO_FILE):
    with open(PROMO_FILE, "w") as f:
        f.write(PREMIUM_APPS_LINK)
if not os.path.exists(GIFT_FILE):
    with open(GIFT_FILE, "w") as f:
        f.write("https://www.canva.com/brand/join?token=BrnBqEuFTwf7IgNrKWfy4A&br")

def get_mode():
    try:
        return open(MODE_FILE).read().strip()
    except Exception:
        return "monetag"

def set_mode(mode: str):
    with open(MODE_FILE, "w") as f:
        f.write(mode.strip())

def get_promo_link():
    try:
        return open(PROMO_FILE).read().strip()
    except Exception:
        return PREMIUM_APPS_LINK

def update_promo_link(link: str):
    with open(PROMO_FILE, "w") as f:
        f.write(link.strip())

def get_gift_link():
    try:
        return open(GIFT_FILE).read().strip()
    except Exception:
        return "https://www.canva.com/brand/join?token=BrnBqEuFTwf7IgNrKWfy4A&br"

def update_gift_link(link: str):
    with open(GIFT_FILE, "w") as f:
        f.write(link.strip())

# -------------------- GLOBAL STORAGE --------------------
GROUP_PINS = {}
PIN_CLICKS = 0

# -------------------- IN-MEM STORAGE --------------------
ad_count = {}          # user_id -> verified ads count (0..TOTAL_ADS)
verified_users = set() # completed users
user_list = set()      # seen users (for broadcast / status)
close_times = {}       # user_id -> timestamp when the client signalled close (beforeunload)

# -------------------- HTML: single ad-watching page (dynamic) --------------------
HTML_PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Canva Premium Access - Watch Ads</title>
<style>
  :root{--bg:#0d0d0d;--card:#121213;--muted:#bdbdbd;--accent1:#7b2ff7;--accent2:#f107a3}
  body{font-family:Inter,Arial; background:var(--bg); color:#fff; margin:0; padding:22px; display:flex;justify-content:center}
  .card{width:100%;max-width:640px;background:var(--card);border-radius:12px;padding:22px;text-align:center}
  .title{font-size:22px;font-weight:800;background:linear-gradient(90deg,var(--accent1),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
  .subtitle{color:var(--muted);margin-bottom:14px}
  .steps{display:flex;gap:8px;justify-content:center;margin:14px 0;flex-wrap:wrap}
  .step{width:46px;height:46px;border-radius:10px;background:#222;display:flex;align-items:center;justify-content:center;font-weight:700;color:#999}
  .step.done{background:linear-gradient(90deg,var(--accent1),var(--accent2));color:#fff}
  .actions{display:flex;flex-direction:column;gap:12px;margin-top:12px;align-items:center}
  .btn{border:none;border-radius:10px;padding:12px 18px;font-weight:700;cursor:pointer;font-size:15px}
  .btn-primary{background:linear-gradient(90deg,var(--accent1),var(--accent2));color:#fff}
  .btn-secondary{background:#1b1b1b;color:#fff;border:1px solid #2a2a2a;padding:10px}
  .credit{margin-top:14px;color:var(--muted);font-size:13px}
  #inactiveMsg{display:none;margin-top:10px;color:#f1c40f}
  iframe#adFrame{width:100%;height:420px;border-radius:10px;border:none;margin-top:12px}
</style>
</head>
<body>
  <div class="card" role="main">
    <div class="title">Canva Premium Access</div>
    <div class="subtitle">Watch {{ total }} Ads to unlock the gift. Bonus links shown below.</div>

    <div class="steps" aria-hidden="true">
      {% for i in range(1, total+1) %}
        <div class="step {% if i <= watched %}done{% endif %}">{{ i }}</div>
      {% endfor %}
    </div>

    <div class="actions" id="actionArea">
      {% if monetag_script %}
        {{ monetag_script | safe }}
      {% endif %}
      {{ watch_button | safe }}

      <div style="width:92%;max-width:480px;margin-top:12px">
        <a class="btn btn-secondary" href="{{ premium_link }}" target="_blank" style="display:block;margin-bottom:8px">Premium Apps</a>
        <a class="btn btn-secondary" href="{{ cheapdata_link }}" target="_blank" style="display:block">Download Cheap Data App</a>
      </div>

      <div id="inactiveMsg">⏳ You were inactive — your progress was reset. Please start again.</div>
    </div>

    <div class="credit">
      <div style="margin-top:12px">💎 <strong>Developed by Ejimurphy</strong></div>
      <div class="small" style="color:var(--muted); margin-top:6px">Promotion / Contact: <strong>@ejimurphy</strong> — Order a bot for $100</div>
    </div>
  </div>

<script>
const INACTIVITY_MS = {{ inactivity_ms }};
const userId = {{ user_id }};
let timer = null;

function tryBeacon(url) {
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url);
    } else {
      fetch(url, { method: 'POST', keepalive:true }).catch(()=>{});
    }
  } catch(e){}
}

function resetOnServer() {
  fetch('/reset_progress/' + userId, { method:'POST' }).finally(()=> location.reload());
}

function showInactiveAndReset(){
  document.getElementById('inactiveMsg').style.display = 'block';
  resetOnServer();
}

function resetTimer(){
  if (timer) clearTimeout(timer);
  document.getElementById('inactiveMsg').style.display = 'none';
  timer = setTimeout(showInactiveAndReset, INACTIVITY_MS);
}

['mousemove','keydown','click','touchstart'].forEach(ev=>{ window.addEventListener(ev, resetTimer, { passive:true }); });
resetTimer();

window.addEventListener('beforeunload', function(){
  try {
    tryBeacon('/mark_closed/' + userId);
  } catch(e){}
});
</script>
<!-- Telega.io Mini App Monetization SDK -->
<script src="https://inapp.telega.io/sdk/v1/sdk.js"></script>
<script>
  const ads = window.TelegaIn.AdsController.create_miniapp({
    token: 'ca7256f5-479b-485c-aee8-a11e0b9d9d5f'
  });
</script>
</body>
</html>
"""

# -------------------- FLASK APP --------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Canva Premium Access bot web endpoint."

@app.route("/user/<int:user_id>")
def user_page(user_id):
    # Check recorded close time: only reset if grace expired
    ct = close_times.get(user_id)
    now_ts = time.time()
    if ct is not None and (now_ts - ct) >= GRACE_SECONDS:
        # grace expired -> reset
        ad_count[user_id] = 0
        verified_users.discard(user_id)
        close_times.pop(user_id, None)
        logger.info("Grace expired for %s: progress reset", user_id)

    watched = ad_count.get(user_id, 0)
    total = get_required_ads()

    monetag_script = ""
    if MONETAG_ZONE:
        monetag_script = f"<script src='//libtl.com/sdk.js' data-zone='{MONETAG_ZONE}' data-sdk='show_{MONETAG_ZONE}'></script>"

    if watched < total:
        next_idx = watched + 1
        # JS button: try SDK first, else open zone and fallback verify
        watch_button = (
            "<button class='btn btn-primary' id='watchBtn' onclick=\"(function(){"
            "var sdkFn = window['show_%s'];"
            "if (typeof sdkFn === 'function') {"
            "  sdkFn().then(function(){"
            "    fetch('/verify_ad/%s/%s', { method:'POST' }).then(function(){ setTimeout(function(){ location.reload(); }, 700); });"
            "  }).catch(function(e){ console.error(e); alert('Ad failed to load.'); });"
            "} else {"
            "  window.open('%s','_blank');"
            "  setTimeout(function(){ fetch('/verify_ad/%s/%s', { method:'POST' }).then(function(){ setTimeout(function(){ location.reload(); }, 700); }); }, 12000);"
            "}"
            "})()\">🎬 Watch Ads to Unlock Gift</button>"
        ) % (MONETAG_ZONE or "", user_id, next_idx, MONETAG_LINK or "#", user_id, next_idx)
    else:
        gift = get_gift_link()
        watch_button = f"<a href='{gift}' target='_blank'><button class='btn btn-primary'>🎁 Access Gift</button></a>"

    return render_template_string(
        HTML_PAGE,
        watched=watched,
        total=get_required_ads(),
        monetag_script=monetag_script,
        watch_button=watch_button,
        premium_link=get_promo_link(),
        cheapdata_link=CHEAP_DATA_LINK,
        user_id=user_id,
        inactivity_ms=INACTIVITY_MS
    )

# Telegram webhook placeholder – prevents 404 on Telegram side
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "POST":
        update = request.get_json(force=True)
        updater = app.config["bot_updater"]
        dp = updater.dispatcher
        dp.process_update(Update.de_json(update, app.config["bot_bot"]))
        return "OK", 200
    return "Webhook OK", 200

@app.route("/verify_ad/<int:user_id>/<int:count>", methods=["POST"])
def verify_ad(user_id, count):
    prev = ad_count.get(user_id, 0)
    total = get_required_ads()
    if count == prev + 1 and count <= total:
        ad_count[user_id] = count
        user_list.add(user_id)
        logger.info("User %s verified ad %d (now %d)", user_id, count, ad_count[user_id])
        if ad_count[user_id] >= total:
            verified_users.add(user_id)
    else:
        logger.info("Ignored verify for user %s: count=%s prev=%s total=%s", user_id, count, prev, total)
    return "ok"

@app.route("/reset_progress/<int:user_id>", methods=["POST"])
def reset_progress(user_id):
    ad_count[user_id] = 0
    verified_users.discard(user_id)
    close_times.pop(user_id, None)
    logger.info("Reset progress for user %s via reset endpoint", user_id)
    return "ok"

@app.route("/mark_closed/<int:user_id>", methods=["POST"])
def mark_closed(user_id):
    close_times[user_id] = time.time()
    logger.info("Marked closed for %s at %s", user_id, datetime.utcfromtimestamp(close_times[user_id]).isoformat())
    return "ok"

# small admin endpoints to view/set ads count
@app.route("/get_ads_count", methods=["GET"])
def get_ads_count():
    return jsonify(status="ok", required_ads=get_required_ads())

@app.route("/set_ads_count", methods=["POST"])
def set_ads_count():
    data = request.get_json(silent=True) or {}
    admin_id = data.get("admin_id")
    if admin_id is None or int(admin_id) not in ADMIN_IDS:
        return jsonify(status="error", message="unauthorized"), 403
    try:
        cnt = int(data.get("count", 0))
        if cnt < 1 or cnt > 100:
            return jsonify(status="error", message="count must be 1..100"), 400
        set_required_ads(cnt)
        return jsonify(status="ok", required_ads=cnt)
    except Exception as e:
        return jsonify(status="error", message=str(e)), 400

# -------------------- TELEGRAM BOT HANDLERS --------------------
def is_admin(uid):
    return int(uid) in ADMIN_IDS

from telegram import BotCommand

def set_user_commands(bot, chat_id):
    bot.set_my_commands(
        [
            BotCommand("start", "Start watching ads"),
            BotCommand("help", "Help"),
        ],
        chat_id=chat_id
    )

def set_group_admin_commands(bot, chat_id):
    bot.set_my_commands(
        [
            BotCommand("start", "Start watching ads"),
            BotCommand("help", "Help"),
            BotCommand("mod_on", "Enable moderation"),
            BotCommand("mod_off", "Disable moderation"),
            BotCommand("warn", "Warn user"),
            BotCommand("unwarn", "Remove warning"),
            BotCommand("warned", "Warned users"),
            BotCommand("ban", "Ban user"),
            BotCommand("unban", "Unban user"),
            BotCommand("banned", "Banned users"),
        ],
        chat_id=chat_id
    )

from telegram import BotCommandScopeAllPrivateChats

def set_owner_commands(bot):
    bot.set_my_commands(
        [
            # Ads Watch
            BotCommand("start", "Start watching ads"),
            BotCommand("help", "Help"),

            # Owner system
            BotCommand("broadcast", "Broadcast message"),
            BotCommand("updategift", "Update gift"),
            BotCommand("getgift", "Get gift"),
            BotCommand("resetads", "Reset ads"),
            BotCommand("setmode", "Set mode"),
            BotCommand("switchmode", "Switch mode"),
            BotCommand("setpromo", "Set promo"),
            BotCommand("currentmode", "Current mode"),
            BotCommand("status", "Bot status"),
            BotCommand("setads", "Set ads"),
            BotCommand("getads", "Get ads"),
            BotCommand("set_monetag_zone", "Set Monetag zone"),

            # 📌 PIN FEATURES (OWNER ONLY)
            BotCommand("sendpin", "Send & pin post to group/channel"),

            # Moderation (owner override)
            BotCommand("mod_on", "Enable moderation"),
            BotCommand("mod_off", "Disable moderation"),
            BotCommand("warn", "Warn user"),
            BotCommand("unwarn", "Unwarn user"),
            BotCommand("warned", "Warned users"),
            BotCommand("ban", "Ban user"),
            BotCommand("unban", "Unban user"),
            BotCommand("banned", "Banned users"),
        ],
        scope=BotCommandScopeAllPrivateChats()
    )

def start_cmd(update, context):
    user = update.effective_user
    chat = update.effective_chat
    bot = context.bot

    # ==========================
    # ROLE-BASED "/" COMMAND MENU
    # ==========================
    if is_bot_owner(user.id):
        set_owner_commands(bot, chat.id)

    elif chat.type in ("group", "supergroup", "channel") and \
         is_group_admin(bot, chat.id, user.id):
        set_group_admin_commands(bot, chat.id)

    else:
        set_user_commands(bot, chat.id)
        
def start_cmd(update, context):
    uid = update.effective_user.id
    ad_count.setdefault(uid, 0)
    user_list.add(uid)

    # Determine web URL
    web = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEB_URL") or f"http://localhost:{os.environ.get('PORT',5000)}"

    # Check for start parameter payload
    payload = context.args[0] if context.args else ""
    if payload.lower() == "startapp":
        update.message.reply_text(
            f"🎬 Welcome! Watch {get_required_ads()} ads to unlock your gift!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Go to Ads", url=f"{web}/user/{uid}")]])
        )
        return

    # Default /start behavior
    keyboard = [[InlineKeyboardButton("🎬 Start Watching Ads", url=f"{web}/user/{uid}")]]
    update.message.reply_text(
        f"Welcome! Mode: {get_mode()}.\nWatch {get_required_ads()} ads to unlock your gift.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def help_cmd(update, context):
    chat = update.effective_chat
    user = update.effective_user

    is_owner = user.id == BOT_OWNER_ID
    is_bot_admin_user = is_bot_admin(user.id)
    is_group_admin_user = (
        chat.type in ("group", "supergroup", "channel")
        and is_group_admin(context.bot, chat.id, user.id)
    )

    text = ""

    # ====================
    # 👤 USER COMMANDS (EVERYONE)
    # ====================
    text += (
        "🤖 *User Commands*\n"
        "/start – Open your ad page\n"
        "/help – Show this help\n\n"
    )

    # ====================
    # 🛡 MODERATION COMMANDS
    # ====================
    if is_group_admin_user or is_bot_admin_user or is_owner:
        text += (
            "🛡 *Moderator Commands*\n"
            "/mod_on – Enable moderation\n"
            "/mod_off – Disable moderation\n"
            "/warn <reply | user_id>\n"
            "/unwarn <reply | user_id>\n"
            "/ban <reply | user_id>\n"
            "/unban <reply | user_id>\n"
            "/warned – List warned users\n"
            "/banned – List banned users\n\n"
        )

    # ====================
    # 👑 BOT ADMIN / OWNER
    # ====================
    if is_bot_admin_user or is_owner:
        text += (
            "👑 *Admin Commands*\n"
            "/updategift <link>\n"
            "/getgift\n"
            "/resetads\n"
            "/broadcast <msg>\n"
            "/setmode <monetag|promo>\n"
            "/switchmode\n"
            "/setpromo <link>\n"
            "/currentmode\n"
            "/status\n"
            "/setads <n>\n"
            "/getads\n"
            "/set_monetag_zone <zone>\n"
        )

    update.message.reply_text(text, parse_mode="Markdown")
    
def updategift_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    if not context.args:
        return update.message.reply_text("Usage: /updategift <link>")
    new = context.args[0]
    update_gift_link(new)
    update.message.reply_text(f"✅ Gift link updated to: {new}")

def getgift_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    update.message.reply_text(f"🎁 Gift link:\n{get_gift_link()}")

def resetads_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    ad_count.clear()
    verified_users.clear()
    close_times.clear()
    update.message.reply_text("✅ All ad progress reset.")

def broadcast_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    if not context.args:
        return update.message.reply_text("Usage: /broadcast <message>")
    message = " ".join(context.args)
    sent = 0
    for uid in list(user_list):
        try:
            context.bot.send_message(chat_id=uid, text=message)
            sent += 1
        except Exception as e:
            logger.info("Broadcast to %s failed: %s", uid, e)
    update.message.reply_text(f"✅ Sent to {sent} users.")

def setmode_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    if not context.args:
        return update.message.reply_text("Usage: /setmode <monetag|promo>")
    mode = context.args[0].lower()
    if mode not in ("monetag", "promo"):
        return update.message.reply_text("⚠️ Invalid mode.")
    set_mode(mode)
    update.message.reply_text(f"✅ Mode set to: {mode}")

def switchmode_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    current = get_mode()
    new = "promo" if current == "monetag" else "monetag"
    set_mode(new)
    update.message.reply_text(f"🔁 Switched from {current} to {new}")

def setpromo_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    if not context.args:
        return update.message.reply_text("Usage: /setpromo <link>")
    update_promo_link(context.args[0])
    update.message.reply_text("✅ Promo link updated.")

def currentmode_cmd(update, context):
    update.message.reply_text(f"🧭 Current mode: {get_mode()}")

def status_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    total_users = len(user_list)
    total_completed = len(verified_users)
    top = sorted(ad_count.items(), key=lambda x: x[1], reverse=True)[:30]
    top_lines = "\n".join([f"{uid}: {cnt}" for uid, cnt in top]) or "No data yet."
    msg = f"📊 Users seen: {total_users}\nCompleted: {total_completed}\n\nTop users:\n{top_lines}"
    update.message.reply_text(msg)

def setads_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    if not context.args or not context.args[0].isdigit():
        return update.message.reply_text("Usage: /setads <number>")
    n = int(context.args[0])
    if n < 1 or n > 100:
        return update.message.reply_text("Choose 1..100")
    set_required_ads(n)
    update.message.reply_text(f"✅ Required ads updated to {n}")

def getads_cmd(update, context):
    update.message.reply_text(f"🎯 Current required ads: {get_required_ads()}")

def set_monetag_zone_cmd(update, context):
    global MONETAG_ZONE, MONETAG_LINK
    if not is_admin(update.effective_user.id):
        return update.message.reply_text("🚫 Admin only.")
    if not context.args:
        return update.message.reply_text("Usage: /set_monetag_zone <zone_id>")
    MONETAG_ZONE = context.args[0].strip()
    MONETAG_LINK = f"https://libtl.com/zone/{MONETAG_ZONE}"
    update.message.reply_text(f"✅ Monetag zone set to {MONETAG_ZONE}")     

def pinpost_cmd(update, context):
    chat = update.effective_chat
    user = update.effective_user

    # ✅ ALLOW CHANNELS
    if chat.type == "channel":
        allowed = True
    else:
        allowed = (
            user and (
                user.id == BOT_OWNER_ID or
                is_group_admin(context.bot, chat.id, user.id)
            )
        )

    if not allowed:
        update.message.reply_text("❌ Admins only")
        return

    if len(context.args) < 2:
        update.message.reply_text(
            "Usage:\n"
            "/pinpost <message_text> | <button_text> | <url>\n\n"
            "Example:\n"
            "/pinpost Premium_Offer | Join_Now | https://t.me/yourchannel"
        )
        return

    # 🧠 Parse message
    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]

    if len(parts) != 3:
        update.message.reply_text("❌ Format error. Use | to separate fields.")
        return

    message_text = parts[0].replace("_", " ")
    button_text = parts[1].replace("_", " ")
    button_url = parts[2]

    pin_with_button(
        context.bot,
        chat.id,
        message_text,
        button_text,
        button_url
    )


def unpinpost_cmd(update, context):
    chat = update.effective_chat
    user = update.effective_user

    # Allow bot owner or admins
    if user.id != BOT_OWNER_ID and not is_group_admin(context.bot, chat.id, user.id):
        update.message.reply_text("❌ Admins only.")
        return

    try:
        context.bot.unpin_chat_message(chat.id)
        update.message.reply_text("✅ Pinned message removed.")
    except Exception as e:
        update.message.reply_text(f"❌ Failed: {e}")

def editpin_cmd(update, context):
    chat = update.effective_chat
    user = update.effective_user

    if user.id != BOT_OWNER_ID and not is_group_admin(context.bot, chat.id, user.id):
        update.message.reply_text("❌ Admins only.")
        return

    if len(context.args) < 2:
        update.message.reply_text(
            "Usage:\n"
            "/editpin <button_text> <link>"
        )
        return

    button_text = context.args[0].replace("_", " ")
    link = context.args[1]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(button_text, url=link)]
    ])

    try:
        pinned = context.bot.get_chat(chat.id).pinned_message
        if not pinned:
            update.message.reply_text("⚠️ No pinned message found.")
            return

        context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=pinned.message_id,
            text="📢 *Updated Announcement*\n\nClick below:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

        update.message.reply_text("✅ Pinned message updated.")

    except Exception as e:
        update.message.reply_text(f"❌ Failed: {e}")

def sendpin_cmd(update, context):
    user = update.effective_user

    # OWNER CHECK
    if not is_bot_owner(user.id):
        update.message.reply_text("❌ Owner only")
        return

    raw = update.message.text

    # Expected format:
    # /sendpin chat_id | text | button_text | url
    if "|" not in raw:
        update.message.reply_text(
            "❌ Format:\n"
            "/sendpin chat_id | text | button_text | url"
        )
        return

    try:
        _, payload = raw.split(" ", 1)
        parts = [p.strip() for p in payload.split("|", 3)]

        if len(parts) != 4:
            raise ValueError("Invalid parts")

        chat_id = int(parts[0])
        text = parts[1]
        button_text = parts[2]
        button_url = parts[3]

    except Exception as e:
        update.message.reply_text(f"❌ Parsing error: {e}")
        return

    # SEND MESSAGE WITH BUTTON
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(button_text, url=button_url)]
        ])

        msg = context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

        # PIN MESSAGE
        context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True
        )

        update.message.reply_text("✅ Post sent and pinned successfully")

    except Exception as e:
        update.message.reply_text(f"❌ Telegram error:\n{e}")

# ------------------ GLOBALS ------------------
WARNED_USERS = {}
BANNED_USERS = {}
violations = {}
MODERATION_ENABLED = {}

LINK_REGEX = re.compile(r"(http://|https://|t\.me/|www\.)", re.IGNORECASE)
MENTION_REGEX = re.compile(r"@\w+")
ALLOWED_MENTION = "@ejimurphy"

# ------------------ HELPERS ------------------
def is_bot_admin(user_id):
    return int(user_id) in ADMIN_IDS


def error_handler(update, context):
    logging.exception(
        "Telegram error:",
        exc_info=context.error
    )

def echo_logger(update, context):
    try:
        user = getattr(update, "effective_user", None)
        text = (getattr(update.message, "text", "") or "")[:200]
        logger.info("Msg from %s: %s", getattr(user, "id", "unknown"), text)
    except Exception:
        logger.exception("echo_logger error")
    # intentionally do NOT reply to every message

def is_group_admin(bot, chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

def is_moderation_enabled(chat_id):
    return MODERATION_ENABLED.get(chat_id, True)

def handle_violation(update, context, reason):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    uid = user.id
    violations[uid] = violations.get(uid, 0) + 1
    count = violations[uid]

    try:
        update.message.delete()
    except:
        pass

    if count == 1:
        WARNED_USERS[uid] = user.first_name
        context.bot.send_message(
            chat_id=chat.id,
            text=f"⚠️ {user.first_name}, warning!\nReason: {reason}\nNext violation = mute."
        )
    elif count == 2:
        context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=uid,
            permissions=telegram.ChatPermissions(can_send_messages=False),
            until_date=int(time.time()) + 86400
        )
        context.bot.send_message(
            chat_id=chat.id,
            text=f"🔇 {user.first_name} has been muted for 24 hours.\nReason: {reason}"
        )
    else:
        BANNED_USERS[uid] = user.first_name
        context.bot.ban_chat_member(chat.id, user_id=uid)
        context.bot.send_message(
            chat_id=chat.id,
            text=f"⛔ {user.first_name} has been banned.\nReason: Repeated violations."
        )

def pin_with_button(bot, chat_id, text, button_text, button_url):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(button_text, url=button_url)]
    ])

    msg = bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

    bot.pin_chat_message(
        chat_id=chat_id,
        message_id=msg.message_id,
        disable_notification=True
    )

def auto_pin_ads(context):
    job = context.job
    chat_id = job.context["chat_id"]

    data = GROUP_PINS.get(chat_id, {
        "text": "🚀 PREMIUM ACCESS AVAILABLE\n\nClick below to join:",
        "link": "https://t.me/yourchannel"
    })

    pin_with_button(
        context.bot,
        chat_id,
        data["text"],
        "VIEW CHANNEL",
        data["link"]
    )


def start_autopin(update, context):
    chat = update.effective_chat
    user = update.effective_user

    if user.id != BOT_OWNER_ID and not is_group_admin(context.bot, chat.id, user.id):
        update.message.reply_text("❌ Admins only")
        return

    context.job_queue.run_repeating(
        auto_pin_ads,
        interval=timedelta(hours=6),
        first=10,
        context={"chat_id": chat.id},
        name=str(chat.id)
    )

    update.message.reply_text("✅ Auto-pin started (every 6 hours)")

def set_pin_button(update, context):
    chat = update.effective_chat
    user = update.effective_user

    if user.id != BOT_OWNER_ID and not is_group_admin(context.bot, chat.id, user.id):
        return

    if len(context.args) < 2:
        update.message.reply_text("/setpin <text> <link>")
        return

    GROUP_PINS[chat.id] = {
        "text": context.args[0].replace("_", " "),
        "link": context.args[1]
    }

    update.message.reply_text("✅ Pin button saved")

def protect_pin(update, context):
    msg = update.effective_message
    chat = update.effective_chat

    if msg and msg.pinned_message:
        user = msg.from_user

        if user and not is_group_admin(context.bot, chat.id, user.id):
            try:
                context.bot.pin_chat_message(
                    chat.id,
                    msg.pinned_message.message_id,
                    disable_notification=True
                )
            except:
                pass

def scheduled_unpin(context):
    chat_id = context.job.context
    context.bot.unpin_chat_message(chat_id)

def schedule_unpin(update, context):
    chat = update.effective_chat
    context.job_queue.run_once(
        scheduled_unpin,
        when=timedelta(hours=12),
        context=chat.id
    )
    update.message.reply_text("⏰ Will unpin in 12 hours")
    
def send_and_pin(bot, chat_id, text, button_text, button_url):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(button_text, url=button_url)]
    ])

    msg = bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

    bot.pin_chat_message(
        chat_id=chat_id,
        message_id=msg.message_id,
        disable_notification=True
    )
    
# ------------------ ADMIN / MODERATION COMMANDS ------------------
def warned_list(update, context):
    if not is_group_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    warned = WARNED_USERS
    if not warned:
        update.message.reply_text("✅ No warned users.")
        return
    text = "⚠️ Warned Users:\n"
    for uid, name in warned.items():
        text += f"- {name} (`{uid}`)\n"
    update.message.reply_text(text, parse_mode="Markdown")

def banned_list(update, context):
    if not is_group_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    banned = BANNED_USERS
    if not banned:
        update.message.reply_text("✅ No banned users.")
        return
    text = "⛔ Banned Users:\n"
    for uid, name in banned.items():
        text += f"- {name} (`{uid}`)\n"
    update.message.reply_text(text, parse_mode="Markdown")

def mod_on(update, context):
    if not is_group_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    MODERATION_ENABLED[update.effective_chat.id] = True
    update.message.reply_text("🟢 Moderation ENABLED for this group")

def mod_off(update, context):
    if not is_group_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    MODERATION_ENABLED[update.effective_chat.id] = False
    update.message.reply_text("🔴 Moderation DISABLED for this group")

def unwarn(update, context):
    if not is_group_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        update.message.reply_text("Usage: /unwarn <user_id>")
        return
    user_id = int(context.args[0])
    WARNED_USERS.pop(user_id, None)
    update.message.reply_text(f"✅ Warning removed for user `{user_id}`", parse_mode="Markdown")

def unban_cmd(update, context):
    chat = update.effective_chat
    user = update.effective_user

    if not is_group_admin(context.bot, chat.id, user.id):
        update.message.reply_text("❌ Admin-only command.")
        return

    # Reply-based unban
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].isdigit():
        target_id = int(context.args[0])
    else:
        update.message.reply_text("⚠️ Usage:\n/unban <user_id>\nOR reply to the user's message with /unban")
        return

    try:
        context.bot.unban_chat_member(chat.id, target_id)
        update.message.reply_text("✅ User has been unbanned.")
    except Exception as e:
        update.message.reply_text(f"❌ Failed to unban: {e}")

# ------------------ MODERATION HANDLER ------------------
def moderation_handler(update, context):
    message = update.effective_message
    if not message:
        return

    chat = update.effective_chat

    # ✅ ALLOW messages sent as channel or group
    if message.sender_chat:
        return

    user = message.from_user
    if not user or not chat:
        return

    # ✅ Ignore bot messages
    if user.is_bot:
        return

    # ✅ Allow bot owner
    if user.id == BOT_OWNER_ID:
        return

    # ✅ Allow bot admins (global admins)
    if is_bot_admin(user.id):
        return

    # ✅ Allow group/channel admins
    if is_group_admin(context.bot, chat.id, user.id):
        return

    text = (message.text or message.caption or "").lower()
    if not text:
        return

    # ✅ Replies are allowed ONLY if clean
    if message.reply_to_message:
    if LINK_REGEX.search(text):
    # allow admins / owner
    if is_group_admin(context.bot, chat.id, user.id) or is_bot_owner(user.id):
        return

    handle_violation(update, context, "Unauthorized link detected")
    return


    # ❌ Block links (normal users)
    if LINK_REGEX.search(text):
        handle_violation(update, context, "Unauthorized link")
        return

    # ❌ Block @mentions (except allowed one)
    mentions = MENTION_REGEX.findall(text)
    for mention in mentions:
        if mention.lower() != ALLOWED_MENTION.lower():
            handle_violation(update, context, "Unauthorized @mention")
            return
    
# ------------------ STRICT MODERATION ------------------
def strict_group_moderation(update, context):
    message = update.effective_message
    if not message:
        return

    chat = update.effective_chat
    if not chat:
        return

    # ✅ ALLOW channel or group identity posts
    if message.sender_chat:
        return

    user = message.from_user
    if not user:
        return

    # ✅ Allow bots
    if user.is_bot:
        return

    # ✅ Allow bot owner
    if user.id == BOT_OWNER_ID:
        return

    # ✅ Allow bot admins
    if is_admin(user.id):
        return

    # ✅ Allow group/channel admins
    if is_group_admin(context.bot, chat.id, user.id):
        return

    # ❌ FROM HERE — NORMAL USERS ONLY

    # Block bot spam
    if is_message_from_bot(message):
        try:
            context.bot.delete_message(chat.id, message.message_id)
            context.bot.ban_chat_member(chat.id, user.id)
        except Exception:
            pass
        return

    # Block links, buttons, mentions
    if contains_forbidden_content(message):
        try:
            context.bot.delete_message(chat.id, message.message_id)
            context.bot.ban_chat_member(chat.id, user.id)
        except Exception:
            pass
        
# ======================================================
# UNIVERSAL JOIN HANDLER (GROUP + CHANNEL + BOT ADDED)
# ======================================================

from telegram import ChatMemberUpdated

welcomed = set()

def handle_join_events(update, context):
    """Handles ALL join events:
       - group joins
       - channel joins
       - user added manually
       - user joins via link
       - bot added to group/channel
       - admin promoted/demoted
    """

    upd = update.to_dict()
    print("\n🔥 RAW JOIN EVENT:", upd, "\n")

    msg = update.message
    chat = update.effective_chat
    bot_id = context.bot.id

    # 1️⃣ GROUP JOIN EVENTS (new_chat_members)
    if msg and msg.new_chat_members:
        for user in msg.new_chat_members:

            # Bot added
            if user.id == bot_id:
                try:
                    msg.reply_text(
                        "🔥 Thanks for adding me!\n"
                        "I will welcome new members with a Canva Premium button 🎁"
                    )
                except: pass
                return

            # Ignore other bots
            if user.is_bot:
                return

            # Unique welcome check
            key = (chat.id, user.id)
            if key in welcomed:
                return
            welcomed.add(key)

            BOT_LINK = "https://t.me/CanvaPro4all_bot?startapp"
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🎁 Get Canva Premium Access", url=BOT_LINK)]]
            )

            msg.reply_text(
                f"🎉 Welcome {user.first_name}!\nTap below to claim Canva Premium Access 👇",
                reply_markup=keyboard
            )
        return

    # 2️⃣ CHANNEL JOIN EVENTS
    if isinstance(update.my_chat_member, ChatMemberUpdated):
        c = update.my_chat_member

        old = c.old_chat_member.status
        new = c.new_chat_member.status

        # Bot added to CHANNEL
        if new in ["member", "administrator"] and c.new_chat_member.user.id == bot_id:
            try:
                context.bot.send_message(
                    chat_id=chat.id,
                    text="🔥 Bot added to channel! I will send join-welcome messages."
                )
            except: pass
            return

        return

   # --------------------------------------------
# FINAL STARTER (Required for Render)
# --------------------------------------------
if __name__ == "__main__":
    from telegram import Bot
    from telegram.utils.request import Request

    # 1) single Bot + Updater (reuse these everywhere)
    bot = Bot(token=TOKEN, request=Request(con_pool_size=8))
    updater = Updater(bot=bot, use_context=True)
    dp = updater.dispatcher

# -------------------- HANDLER REGISTRATION --------------------

# ====================
# 1️⃣ COMMAND HANDLERS
# ====================
dp.add_handler(CommandHandler("start", start_cmd))
dp.add_handler(CommandHandler("help", help_cmd))
dp.add_handler(CommandHandler("updategift", updategift_cmd))
dp.add_handler(CommandHandler("getgift", getgift_cmd))
dp.add_handler(CommandHandler("resetads", resetads_cmd))
dp.add_handler(CommandHandler("broadcast", broadcast_cmd))
dp.add_handler(CommandHandler("setmode", setmode_cmd))
dp.add_handler(CommandHandler("switchmode", switchmode_cmd))
dp.add_handler(CommandHandler("setpromo", setpromo_cmd))
dp.add_handler(CommandHandler("currentmode", currentmode_cmd))
dp.add_handler(CommandHandler("status", status_cmd))
dp.add_handler(CommandHandler("setads", setads_cmd))
dp.add_handler(CommandHandler("getads", getads_cmd))
dp.add_handler(CommandHandler("set_monetag_zone", set_monetag_zone_cmd))
dp.add_handler(CommandHandler("warned", warned_list))
dp.add_handler(CommandHandler("banned", banned_list))
dp.add_handler(CommandHandler("unwarn", unwarn))
dp.add_handler(CommandHandler("mod_on", mod_on))
dp.add_handler(CommandHandler("mod_off", mod_off))
dp.add_handler(CommandHandler("unban", unban_cmd))
dp.add_handler(CommandHandler("pinpost", pinpost_cmd))
dp.add_handler(CommandHandler("unpinpost", unpinpost_cmd))
dp.add_handler(CommandHandler("editpin", editpin_cmd))
dp.add_handler(CommandHandler("autopin", start_autopin))
dp.add_handler(CommandHandler("setpin", set_pin_button))
dp.add_handler(MessageHandler(Filters.status_update.pinned_message, protect_pin), group=0)
dp.add_handler(CommandHandler("scheduleunpin", schedule_unpin))
dp.add_handler(CommandHandler("sendpin", sendpin_cmd))

# ====================
# 2️⃣ JOIN HANDLERS (EARLY)
# ====================
try:
    from telegram.ext import ChatMemberHandler
    dp.add_handler(
        ChatMemberHandler(handle_join_events, ChatMemberHandler.CHAT_MEMBER),
        group=0
    )
except Exception:
    logger.info("ChatMemberHandler not available; relying on fallback.")

dp.add_handler(
    MessageHandler(Filters.status_update.new_chat_members, handle_join_events),
    group=0
)


# ====================
# 3️⃣ NORMAL MODERATION (WARN / MUTE / BAN LOGIC)
# ====================
dp.add_handler(
    MessageHandler(Filters.text & ~Filters.command, moderation_handler),
    group=1
)


# ====================
# 4️⃣ STRICT GROUP MODERATION (LAST LINE OF DEFENSE)
# ====================
dp.add_handler(
    MessageHandler(Filters.group & ~Filters.command, strict_group_moderation),
    group=2
)


# ====================
# 5️⃣ LOGGER (ABSOLUTELY LAST)
# ====================
dp.add_handler(
    MessageHandler(Filters.text & ~Filters.command, echo_logger),
    group=3
)


# ====================
# 6️⃣ GLOBAL ERROR HANDLER
# ====================
updater.dispatcher.add_error_handler(error_handler)

# ------------------------------
# Webhook configuration for Render
# ------------------------------
# Expose bot + updater to the Flask webhook route already defined above
app.config["bot_bot"] = bot
app.config["bot_updater"] = updater

# Build webhook URL from environment (Render provides HTTPS domain)
WEB_URL = os.environ.get("RENDER_EXTERNAL_URL")
if not WEB_URL:
    logger.error("RENDER_EXTERNAL_URL is not set. Webhook won't be configured.")
else:
    webhook_url = f"{WEB_URL.rstrip('/')}/webhook"
    try:
        # Remove any previously set webhook and set the new one
        bot.delete_webhook()
        bot.set_webhook(url=webhook_url)
        logger.info("✅ Webhook set to: %s", webhook_url)
    except Exception as e:
        logger.exception("Failed to set webhook: %s", e)


# ==============================
# REGISTER / COMMAND MENUS HERE
# ==============================
from telegram import BotCommand

# 👤 Normal users (everyone)
def set_user_commands(bot, chat_id):
    bot.set_my_commands(
        [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Help"),
        ],
        chat_id=chat_id
    )

# 🛡 Group / Channel admins
def set_admin_commands(bot, chat_id):
    bot.set_my_commands(
        [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Help"),
            BotCommand("mod_on", "Enable moderation"),
            BotCommand("mod_off", "Disable moderation"),
            BotCommand("warn", "Warn a user"),
            BotCommand("unwarn", "Remove warning"),
            BotCommand("warned", "List warned users"),
            BotCommand("ban", "Ban a user"),
            BotCommand("unban", "Unban a user"),
            BotCommand("banned", "List banned users"),
        ],
        chat_id=chat_id
    )

# 👑 Bot owner (private chat only)
def set_owner_commands(bot, chat_id):
    bot.set_my_commands(
        [
            BotCommand("start", "Start bot"),
            BotCommand("help", "Owner help"),
            BotCommand("broadcast", "Broadcast"),
            BotCommand("updategift", "Update gift"),
            BotCommand("getgift", "Get gift"),
            BotCommand("resetads", "Reset ads"),
            BotCommand("setmode", "Set mode"),
            BotCommand("switchmode", "Switch mode"),
            BotCommand("setpromo", "Set promo"),
            BotCommand("currentmode", "Current mode"),
            BotCommand("status", "Bot status"),
            BotCommand("setads", "Set ads"),
            BotCommand("getads", "Get ads"),
            BotCommand("set_monetag_zone", "Set Monetag zone"),
        ],
        chat_id=chat_id
    )

# Note: we DON'T call updater.start_webhook() here because the Flask route
# will receive and dispatch incoming updates (updater.dispatcher.process_update).
# Start the Flask app (Render will bind to the PORT)
port = int(os.environ.get("PORT", 5000))
logger.info("Starting Flask (and webhook receiver) on port %s", port)
app.run(host="0.0.0.0", port=port)
