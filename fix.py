#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          ⚡ SIMRAN HOSTING PANEL v4.0 - ULTRA ⚡             ║
║   VIP • SQLite • Env Vars • Backup • Monitor • Broadcast    ║
╚══════════════════════════════════════════════════════════════╝
"""

import os, sys, json, sqlite3, telebot, subprocess, zipfile
import shutil, time, signal, threading, psutil
from telebot import types
from datetime import datetime
from io import BytesIO

# ═══════════════ CONFIG ═══════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "8815639801:AAFigOCt3G2PE7NKW718vqckt5ofUGRHsLQ")
OWNER_ID = int(os.getenv("OWNER_ID", "7316506686"))
HEALTH_CHECK_INTERVAL = 45
PENDING_TIMEOUT = 300
CRASH_CHECK_DELAY = 4
FREE_BOT_LIMIT = 2
VIP_BOT_LIMIT = 10
# ═══════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_DIR = os.path.join(BASE_DIR, "hosted_bots")
PENDING_DIR = os.path.join(BASE_DIR, "pending_uploads")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "simran.db")

for d in [HOST_DIR, PENDING_DIR, DATA_DIR]:
    os.makedirs(d, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
RUNNING_BOTS = {}
BOT_LOCK = threading.Lock()
PENDING = {}
PENDING_LOCK = threading.Lock()
START_TIME = time.time()

CODE_NAMES = ['main.py', 'bot.py', 'app.py', 'run.py', 'start.py',
              'index.js', 'bot.js', 'app.js', 'server.js', 'main.js', 'index.mjs']
SUPPORTED_EXT = ('.py', '.js', '.ts', '.mjs', '.cjs')

# ═══════════════ DATABASE ═══════════════
def db_init():
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        uid INTEGER PRIMARY KEY, name TEXT, vip_until TEXT,
        total_bots INTEGER DEFAULT 0, joined TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stats (
        key TEXT PRIMARY KEY, value INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS restarts (
        bot_key TEXT PRIMARY KEY, count INTEGER DEFAULT 0)""")
    con.commit(); con.close()

def db_user(uid, name=""):
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    c.execute("SELECT uid FROM users WHERE uid=?", (uid,))
    if not c.fetchone():
        c.execute("INSERT INTO users(uid,name,joined) VALUES(?,?,?)",
                  (uid, name, datetime.now().isoformat()))
        con.commit()
    con.close()

def is_vip(uid):
    if uid == OWNER_ID: return True
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    c.execute("SELECT vip_until FROM users WHERE uid=?", (uid,))
    row = c.fetchone(); con.close()
    if not row or not row[0]: return False
    try: return datetime.fromisoformat(row[0]) > datetime.now()
    except: return False

def set_vip(uid, days):
    from datetime import timedelta
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    db_user(uid)
    exp = datetime.now() + timedelta(days=days)
    c.execute("UPDATE users SET vip_until=? WHERE uid=?", (exp.isoformat(), uid))
    con.commit(); con.close()

def remove_vip(uid):
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    c.execute("UPDATE users SET vip_until=NULL WHERE uid=?", (uid,))
    con.commit(); con.close()

def get_bot_limit(uid):
    return VIP_BOT_LIMIT if is_vip(uid) else FREE_BOT_LIMIT

def count_user_bots(uid):
    return len([d for d in os.listdir(HOST_DIR)
                if d.startswith(f"{uid}_") and os.path.isdir(os.path.join(HOST_DIR, d))])

def increment_restart(bot_key):
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    c.execute("INSERT OR IGNORE INTO restarts(bot_key,count) VALUES(?,0)", (bot_key,))
    c.execute("UPDATE restarts SET count=count+1 WHERE bot_key=?", (bot_key,))
    con.commit(); con.close()

def get_restart_count(bot_key):
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    c.execute("SELECT count FROM restarts WHERE bot_key=?", (bot_key,))
    row = c.fetchone(); con.close()
    return row[0] if row else 0

# ═══════════════ STYLE ═══════════════
def header():
    return (
        "╔══════════════════════════════════╗\n"
        "║   ⚡ <b>SIMRAN HOSTING v4.0</b> ⚡     ║\n"
        "║   <i>VIP • FAST • 24/7 ONLINE</i>    ║\n"
        "╚══════════════════════════════════╝"
    )

def main_menu(uid):
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(types.InlineKeyboardButton("📦 Classic Upload", callback_data="menu_classic"))
    mk.add(types.InlineKeyboardButton("📤 Any File Upload", callback_data="menu_any"))
    mk.add(types.InlineKeyboardButton("🗜 ZIP Upload", callback_data="menu_zip"))
    mk.add(types.InlineKeyboardButton("🤖 My Bots", callback_data="menu_bots"))
    mk.add(types.InlineKeyboardButton("💎 My Plan", callback_data="menu_plan"))
    mk.add(types.InlineKeyboardButton("📊 Live Stats", callback_data="menu_stats"))
    if uid == OWNER_ID:
        mk.add(types.InlineKeyboardButton("🛡 Admin Panel", callback_data="menu_admin"))
    return mk

def back_menu():
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🔙 Back", callback_data="menu_main"))
    return mk

# ═══════════════ HELPERS ═══════════════
def get_entry_file(bot_dir):
    info = os.path.join(bot_dir, "info.txt")
    if os.path.exists(info):
        with open(info) as f: return f.read().strip()
    for n in CODE_NAMES:
        if os.path.exists(os.path.join(bot_dir, n)): return n
    return None

def spawn_bot(bot_key):
    bot_dir = os.path.join(HOST_DIR, bot_key)
    if not os.path.exists(bot_dir): return None
    entry = get_entry_file(bot_dir)
    if not entry: return None
    if entry.endswith('.py'):
        cmd = [sys.executable, entry]
    else:
        cmd = ['node', entry]
    log_path = os.path.join(bot_dir, "bot.log")
    try:
        lf = open(log_path, 'ab')
        env = os.environ.copy()
        envf = os.path.join(bot_dir, ".env")
        if os.path.exists(envf):
            with open(envf) as f:
                for line in f:
                    line = line.strip()
                    if line and '=' in line and not line.startswith('#'):
                        k, v = line.split('=', 1)
                        env[k.strip()] = v.strip()
        proc = subprocess.Popen(cmd, cwd=bot_dir, stdout=lf,
                                stderr=subprocess.STDOUT,
                                preexec_fn=os.setsid, env=env)
        lf.close()
        return proc
    except Exception as e:
        print(f"[spawn] {bot_key}: {e}")
        return None

def kill_bot(bot_key):
    info = RUNNING_BOTS.get(bot_key)
    if not info: return
    try:
        os.killpg(os.getpgid(info["proc"].pid), signal.SIGTERM)
        time.sleep(0.4)
        if info["proc"].poll() is None:
            os.killpg(os.getpgid(info["proc"].pid), signal.SIGKILL)
    except: pass

def read_log_tail(bot_dir, n=1400):
    p = os.path.join(bot_dir, "bot.log")
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END); size = f.tell()
            f.seek(max(0, size - n))
            return f.read().decode(errors='ignore')
    except: return "No logs yet."

def safe_filename(name):
    return "".join(c for c in name if c.isalnum() or c in "._-")

def unique_bot_key(uid, base):
    base_key = f"{uid}_{base}"
    if not os.path.exists(os.path.join(HOST_DIR, base_key)): return base_key
    i = 1
    while os.path.exists(os.path.join(HOST_DIR, f"{base_key}_{i}")): i += 1
    return f"{base_key}_{i}"

def get_bot_resources(bot_key):
    """CPU/RAM usage for bot process"""
    info = RUNNING_BOTS.get(bot_key)
    if not info: return None
    try:
        p = psutil.Process(info["proc"].pid)
        with p.oneshot():
            return {
                "cpu": round(p.cpu_percent(interval=0.1), 1),
                "ram": round(p.memory_info().rss / 1024 / 1024, 1),
                "uptime": int(time.time() - p.create_time())
            }
    except: return None

# ═══════════════ BACKGROUND ═══════════════
def crash_watchdog():
    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)
        with BOT_LOCK:
            for bk, info in list(RUNNING_BOTS.items()):
                proc = info.get("proc")
                if proc and proc.poll() is not None:
                    print(f"⚠️ {bk} crashed → restarting")
                    increment_restart(bk)
                    new = spawn_bot(bk)
                    if new:
                        RUNNING_BOTS[bk] = {"proc": new, "dir": info["dir"]}
                        # notify user
                        try:
                            uid = int(bk.split("_")[0])
                            bot.send_message(uid,
                                f"⚠️ <b>Bot Crashed & Auto-Restarted</b>\n"
                                f"📦 <code>{bk}</code>\n"
                                f"🔄 Restart Count: {get_restart_count(bk)}")
                        except: pass
                    else:
                        RUNNING_BOTS.pop(bk, None)

def pending_cleanup():
    while True:
        time.sleep(60)
        now = time.time()
        with PENDING_LOCK:
            for uid, p in list(PENDING.items()):
                if now - p.get("ts", now) > PENDING_TIMEOUT:
                    shutil.rmtree(os.path.join(PENDING_DIR, str(uid)), ignore_errors=True)
                    PENDING.pop(uid, None)

# ═══════════════ DEPLOY ═══════════════
def _start_and_report(chat_id, uid, bot_key, entry, bot_dir, msg_id):
    with BOT_LOCK:
        if bot_key in RUNNING_BOTS:
            kill_bot(bot_key); RUNNING_BOTS.pop(bot_key, None)
    proc = spawn_bot(bot_key)
    if not proc:
        try: bot.edit_message_text("❌ Failed to start.", chat_id, msg_id)
        except: pass
        return
    with BOT_LOCK:
        RUNNING_BOTS[bot_key] = {"proc": proc, "dir": bot_dir}
    def check():
        time.sleep(CRASH_CHECK_DELAY)
        if proc.poll() is not None:
            out = read_log_tail(bot_dir)
            with BOT_LOCK: RUNNING_BOTS.pop(bot_key, None)
            try:
                bot.edit_message_text(f"❌ <b>Bot Crashed!</b>\n\n<code>{out[-700:]}</code>", chat_id, msg_id)
            except: pass
        else:
            try:
                bot.edit_message_text(
                    f"✅ <b>Bot Started Successfully!</b>\n\n"
                    f"📦 Entry: <code>{entry}</code>\n"
                    f"🟢 24/7 Running\n"
                    f"💡 Manage in /start → My Bots",
                    chat_id, msg_id, reply_markup=main_menu(uid))
            except: pass
    threading.Thread(target=check, daemon=True).start()

def deploy_from_pending(chat_id, uid):
    with PENDING_LOCK: p = PENDING.pop(uid, None)
    if not p or "py" not in p: return
    py_path, py_name = p["py"], p["py_name"]
    json_path = p.get("json")
    safe = safe_filename(py_name) or "bot.py"
    base = safe.rsplit('.', 1)[0] if '.' in safe else safe
    bot_key = unique_bot_key(uid, base)
    bot_dir = os.path.join(HOST_DIR, bot_key)
    with BOT_LOCK:
        if bot_key in RUNNING_BOTS:
            kill_bot(bot_key); RUNNING_BOTS.pop(bot_key, None)
    if os.path.exists(bot_dir): shutil.rmtree(bot_dir, ignore_errors=True)
    os.makedirs(bot_dir, exist_ok=True)
    try:
        shutil.move(py_path, os.path.join(bot_dir, py_name))
        if json_path and os.path.exists(json_path):
            shutil.move(json_path, os.path.join(bot_dir, "account.json"))
    except Exception as e:
        bot.send_message(chat_id, f"❌ Move fail: {e}"); return
    with open(os.path.join(bot_dir, "info.txt"), "w") as f: f.write(py_name)
    shutil.rmtree(os.path.join(PENDING_DIR, str(uid)), ignore_errors=True)
    msg = bot.send_message(chat_id, "🚀 Starting...")
    _start_and_report(chat_id, uid, bot_key, py_name, bot_dir, msg.message_id)

# ═══════════════ HANDLERS ═══════════════
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    db_user(uid, message.from_user.first_name)
    vip = "💎 VIP" if is_vip(uid) else "🆓 Free"
    text = (f"{header()}\n\n"
            f"👋 Welcome <b>{message.from_user.first_name}</b>!\n"
            f"🎫 Plan: {vip}\n"
            f"📊 Bots: {count_user_bots(uid)}/{get_bot_limit(uid)}\n\n"
            "🔥 <b>SELECT OPTION</b> 👇")
    bot.send_message(message.chat.id, text, reply_markup=main_menu(uid))

@bot.message_handler(commands=['cancel'])
def cancel_cmd(message):
    uid = message.from_user.id
    with PENDING_LOCK: p = PENDING.pop(uid, None)
    shutil.rmtree(os.path.join(PENDING_DIR, str(uid)), ignore_errors=True)
    bot.reply_to(message, "✅ Cancelled" if p else "ℹ️ Nothing pending.")

@bot.callback_query_handler(func=lambda c: True)
def cb(call):
    uid, data = call.from_user.id, call.data
    chat_id, msg_id = call.message.chat.id, call.message.message_id
    try: bot.answer_callback_query(call.id)
    except: pass

    if data == "menu_main":
        with PENDING_LOCK: PENDING.pop(uid, None)
        vip = "💎 VIP" if is_vip(uid) else "🆓 Free"
        bot.edit_message_text(f"{header()}\n\n🎫 {vip} | 📊 Bots: {count_user_bots(uid)}/{get_bot_limit(uid)}\n\n<i>Select option 👇</i>",
                              chat_id, msg_id, reply_markup=main_menu(uid))

    elif data == "menu_classic":
        with PENDING_LOCK: PENDING[uid] = {"mode": "classic", "ts": time.time()}
        bot.edit_message_text("📦 <b>CLASSIC UPLOAD</b>\n\n1️⃣ bot.py bhejo\n2️⃣ account.json bhejo\n\n🚀 Auto-start!",
                              chat_id, msg_id, reply_markup=back_menu())

    elif data == "menu_any":
        with PENDING_LOCK: PENDING[uid] = {"mode": "any", "ts": time.time()}
        bot.edit_message_text("📤 <b>ANY FILE</b>\n\n.py/.js/.ts bhejo\naccount.json optional",
                              chat_id, msg_id, reply_markup=back_menu())

    elif data == "menu_zip":
        bot.edit_message_text("🗜 <b>ZIP UPLOAD</b>\n\nPura project .zip me bhejo\nAuto-detect entry file",
                              chat_id, msg_id, reply_markup=back_menu())

    elif data == "menu_bots":
        show_my_bots(chat_id, msg_id, uid)

    elif data == "menu_plan":
        vip = is_vip(uid)
        text = (f"💎 <b>MY PLAN</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎫 Status: {'💎 VIP' if vip else '🆓 Free'}\n"
                f"🤖 Bot Limit: {get_bot_limit(uid)}\n"
                f"📊 Used: {count_user_bots(uid)}\n\n"
                + ("✅ Unlimited restarts\n✅ Priority support\n✅ All features unlocked"
                   if vip else f"⬆️ Upgrade to VIP for {VIP_BOT_LIMIT} bots!\n📩 Contact @x4x_arjun"))
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=back_menu())

    elif data == "menu_stats":
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        uptime = int(time.time() - START_TIME)
        text = (f"📊 <b>LIVE SERVER STATS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"🖥 CPU: <b>{cpu}%</b>\n"
                f"💾 RAM: <b>{ram.percent}%</b> ({ram.used//1024//1024}MB/{ram.total//1024//1024}MB)\n"
                f"🤖 Running Bots: <b>{len(RUNNING_BOTS)}</b>\n"
                f"⏱ Uptime: <b>{uptime//3600}h {(uptime%3600)//60}m</b>")
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=back_menu())

    elif data == "menu_admin":
        if uid != OWNER_ID: return
        con = sqlite3.connect(DB_PATH); c = con.cursor()
        c.execute("SELECT COUNT(*) FROM users"); total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE vip_until > ?", (datetime.now().isoformat(),))
        vips = c.fetchone()[0]; con.close()
        text = (f"🛡 <b>ADMIN PANEL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 Users: <b>{total}</b>\n💎 VIPs: <b>{vips}</b>\n"
                f"🤖 Running: <b>{len(RUNNING_BOTS)}</b>\n"
                f"📁 Total Bots: <b>{len(os.listdir(HOST_DIR))}</b>\n\n"
                "Commands:\n/vipadd UID DAYS\n/vipdel UID\n/users\n/broadcast MSG")
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=back_menu())

    elif data.startswith("start_"): start_bot(chat_id, msg_id, uid, data[6:])
    elif data.startswith("stop_"): stop_bot(chat_id, msg_id, uid, data[5:])
    elif data.startswith("restart_"): restart_bot(chat_id, msg_id, uid, data[8:])
    elif data.startswith("logs_"): show_logs(chat_id, msg_id, uid, data[5:])
    elif data.startswith("del_"): delete_bot(chat_id, msg_id, uid, data[4:])
    elif data.startswith("env_"): prompt_env(chat_id, msg_id, uid, data[4:])

@bot.message_handler(content_types=['document'])
def handle_upload(message):
    uid = message.from_user.id
    db_user(uid, message.from_user.first_name)
    doc = message.document
    fname = (doc.file_name or "").lower()

    if fname.endswith('.zip'):
        return handle_zip(message)

    with PENDING_LOCK:
        p = PENDING.get(uid); mode = p.get("mode") if p else None

    if not mode:
        return bot.reply_to(message, "⚠️ Pehle menu se option select karo.", reply_markup=main_menu(uid))

    # Check bot limit
    if count_user_bots(uid) >= get_bot_limit(uid):
        return bot.reply_to(message,
            f"❌ <b>Limit Reached!</b>\n\n"
            f"📊 {count_user_bots(uid)}/{get_bot_limit(uid)} bots\n"
            f"💎 VIP le: @x4x_arjun")

    if not (fname.endswith(SUPPORTED_EXT) or fname.endswith('.json')):
        return bot.reply_to(message, "❌ Invalid file type.")

    try:
        fi = bot.get_file(doc.file_id)
        data = bot.download_file(fi.file_path)
    except Exception as e:
        return bot.reply_to(message, f"❌ Download fail: {e}\n<i>(Telegram 20MB limit)</i>")

    updir = os.path.join(PENDING_DIR, str(uid))
    os.makedirs(updir, exist_ok=True)
    is_json = fname.endswith('.json')

    with PENDING_LOCK:
        p = PENDING.get(uid, {"mode": mode, "ts": time.time()})
        p["ts"] = time.time(); p["mode"] = mode
        if is_json:
            dst = os.path.join(updir, "account.json")
            with open(dst, "wb") as f: f.write(data)
            p["json"] = dst
        else:
            if mode == "classic" and not fname.endswith('.py'):
                return bot.reply_to(message, "❌ Classic mode sirf .py")
            safe = safe_filename(doc.file_name) or "bot.py"
            dst = os.path.join(updir, safe)
            with open(dst, "wb") as f: f.write(data)
            p["py"] = dst; p["py_name"] = safe
        PENDING[uid] = p

    with PENDING_LOCK:
        p2 = PENDING.get(uid, {})
        has_code, has_json = "py" in p2, "json" in p2

    if mode == "classic":
        if has_code and has_json: deploy_from_pending(message.chat.id, uid)
        elif is_json: bot.reply_to(message, "✅ account.json mila! Ab bot.py bhejo.")
        else: bot.reply_to(message, f"✅ {doc.file_name} mila! Ab account.json bhejo.")
    else:
        if has_code: deploy_from_pending(message.chat.id, uid)
        else: bot.reply_to(message, "✅ account.json mila! Ab code file bhejo.")

def handle_zip(message):
    uid = message.from_user.id
    if count_user_bots(uid) >= get_bot_limit(uid):
        return bot.reply_to(message, f"❌ Limit reached! VIP le: @x4x_arjun")
    doc = message.document
    fname = doc.file_name or "bot.zip"
    mb = (doc.file_size or 0) / 1024 / 1024
    if mb > 20:
        return bot.reply_to(message, f"❌ File >20MB. Telegram limit.")
    msg = bot.reply_to(message, f"📥 Downloading ({mb:.2f}MB)...")
    bdir = None
    try:
        fi = bot.get_file(doc.file_id)
        data = bot.download_file(fi.file_path)
        bot.edit_message_text("📦 Extracting...", message.chat.id, msg.message_id)
        base = safe_filename(fname.rsplit('.', 1)[0]) or "bot"
        bk = unique_bot_key(uid, base)
        bdir = os.path.join(HOST_DIR, bk)
        os.makedirs(bdir, exist_ok=True)
        zp = os.path.join(bdir, "_up.zip")
        with open(zp, 'wb') as f: f.write(data)
        absd = os.path.abspath(bdir)
        with zipfile.ZipFile(zp, 'r') as zf:
            for m in zf.namelist():
                mp = os.path.abspath(os.path.join(bdir, m))
                if not mp.startswith(absd + os.sep) and mp != absd:
                    raise Exception(f"Unsafe: {m}")
            zf.extractall(bdir)
        os.remove(zp)
        # detect entry
        ef, ed = None, None
        for root, dirs, files in os.walk(bdir):
            dirs[:] = [d for d in dirs if d != '__MACOSX']
            for n in CODE_NAMES:
                if n in files: ef, ed = n, root; break
            if ef: break
        if not ef:
            bot.edit_message_text("❌ No entry file in ZIP.", message.chat.id, msg.message_id)
            shutil.rmtree(bdir, ignore_errors=True); return
        if ed and os.path.abspath(ed) != absd:
            for it in os.listdir(ed):
                s = os.path.join(ed, it); d = os.path.join(bdir, it)
                if os.path.exists(d):
                    shutil.rmtree(d) if os.path.isdir(d) else os.remove(d)
                shutil.move(s, d)
            shutil.rmtree(ed, ignore_errors=True)
        for j in ['__MACOSX', '.DS_Store', 'Thumbs.db']:
            jp = os.path.join(bdir, j)
            if os.path.exists(jp):
                shutil.rmtree(jp) if os.path.isdir(jp) else os.remove(jp)
        with open(os.path.join(bdir, "info.txt"), "w") as f: f.write(ef)
        fc = sum(len(files) for _, _, files in os.walk(bdir))
        bot.edit_message_text(f"✅ Extracted! Entry: <code>{ef}</code> | Files: {fc}\n🚀 Starting...",
                              message.chat.id, msg.message_id)
        _start_and_report(message.chat.id, uid, bk, ef, bdir, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ ZIP fail: {str(e)}", message.chat.id, msg.message_id)
        if bdir: shutil.rmtree(bdir, ignore_errors=True)

def show_my_bots(chat_id, msg_id, uid):
    bots = [d for d in os.listdir(HOST_DIR) if d.startswith(f"{uid}_") and os.path.isdir(os.path.join(HOST_DIR, d))]
    text = f"{header()}\n\n🤖 <b>YOUR BOTS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    mk = types.InlineKeyboardMarkup()
    if not bots:
        text += "❌ Koi bot nahi.\n"
        mk.add(types.InlineKeyboardButton("🔙 Back", callback_data="menu_main"))
    else:
        for b in bots:
            with BOT_LOCK: run = b in RUNNING_BOTS
            st = "🟢 Running" if run else "🔴 Stopped"
            disp = b.replace(f"{uid}_", "")
            res = get_bot_resources(b) if run else None
            rinfo = f" | 💾 {res['ram']}MB" if res else ""
            text += f"📦 <b>{disp}</b> — {st}{rinfo}\n"
            if run:
                mk.row(
                    types.InlineKeyboardButton("⏹ Stop", callback_data=f"stop_{b}"),
                    types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{b}"))
            else:
                mk.row(types.InlineKeyboardButton(f"▶️ Start {disp}", callback_data=f"start_{b}"))
            mk.row(
                types.InlineKeyboardButton("📜 Logs", callback_data=f"logs_{b}"),
                types.InlineKeyboardButton("⚙️ Env", callback_data=f"env_{b}"),
                types.InlineKeyboardButton("🗑 Delete", callback_data=f"del_{b}"))
        mk.add(types.InlineKeyboardButton("🔙 Back", callback_data="menu_main"))
    bot.edit_message_text(text, chat_id, msg_id, reply_markup=mk)

def start_bot(c, m, uid, bk):
    bd = os.path.join(HOST_DIR, bk)
    if not os.path.exists(bd): return
    with BOT_LOCK:
        if bk in RUNNING_BOTS:
            return bot.edit_message_text("⚠️ Already running.", c, m, reply_markup=back_menu())
    entry = get_entry_file(bd) or "?"
    bot.edit_message_text("🚀 Starting...", c, m)
    _start_and_report(c, uid, bk, entry, bd, m)

def stop_bot(c, m, uid, bk):
    with BOT_LOCK:
        if bk in RUNNING_BOTS: kill_bot(bk); RUNNING_BOTS.pop(bk, None)
    show_my_bots(c, m, uid)

def restart_bot(c, m, uid, bk):
    with BOT_LOCK:
        if bk in RUNNING_BOTS: kill_bot(bk); RUNNING_BOTS.pop(bk, None)
    bot.edit_message_text("🔄 Restarting...", c, m)
    entry = get_entry_file(os.path.join(HOST_DIR, bk)) or "?"
    _start_and_report(c, uid, bk, entry, os.path.join(HOST_DIR, bk), m)

def show_logs(c, m, uid, bk):
    logs = read_log_tail(os.path.join(HOST_DIR, bk), 1600)
    disp = bk.replace(f"{uid}_", "")
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🔙 Back", callback_data="menu_bots"))
    bot.edit_message_text(f"📜 <b>LOGS — {disp}</b>\n\n<code>{logs[-1500:]}</code>",
                          c, m, reply_markup=mk)

def delete_bot(c, m, uid, bk):
    with BOT_LOCK:
        if bk in RUNNING_BOTS: kill_bot(bk); RUNNING_BOTS.pop(bk, None)
    shutil.rmtree(os.path.join(HOST_DIR, bk), ignore_errors=True)
    show_my_bots(c, m, uid)

def prompt_env(c, m, uid, bk):
    bot.edit_message_text(
        f"⚙️ <b>ENV VARS — {bk}</b>\n\n"
        f"Ab .env format me bhejo:\n"
        f"<code>API_KEY=abc123\nTOKEN=xyz</code>\n\n"
        f"Reply to this message.",
        c, m, reply_markup=back_menu())
    bot.register_next_step_handler_by_chat_id(c, lambda msg: save_env(msg, bk))

def save_env(msg, bk):
    bd = os.path.join(HOST_DIR, bk)
    if not os.path.exists(bd):
        return bot.reply_to(msg, "❌ Bot not found.")
    with open(os.path.join(bd, ".env"), "w") as f:
        f.write(msg.text or "")
    bot.reply_to(msg, "✅ Env saved. Restart bot to apply.")

# ═══════════════ ADMIN COMMANDS ═══════════════
@bot.message_handler(commands=['vipadd'])
def vipadd(m):
    if m.from_user.id != OWNER_ID: return
    try:
        _, uid, days = m.text.split()
        set_vip(int(uid), int(days))
        bot.reply_to(m, f"✅ VIP added to {uid} for {days} days")
    except: bot.reply_to(m, "Usage: /vipadd UID DAYS")

@bot.message_handler(commands=['vipdel'])
def vipdel(m):
    if m.from_user.id != OWNER_ID: return
    try:
        _, uid = m.text.split()
        remove_vip(int(uid))
        bot.reply_to(m, f"❌ VIP removed from {uid}")
    except: bot.reply_to(m, "Usage: /vipdel UID")

@bot.message_handler(commands=['users'])
def users_cmd(m):
    if m.from_user.id != OWNER_ID: return
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    c.execute("SELECT uid, name, vip_until FROM users ORDER BY uid DESC LIMIT 30")
    rows = c.fetchall(); con.close()
    text = "👥 <b>USERS</b>\n\n"
    for uid, name, vip in rows:
        v = "💎" if vip and datetime.fromisoformat(vip) > datetime.now() else "🆓"
        text += f"{v} <code>{uid}</code> — {name}\n"
    bot.send_message(m.chat.id, text)

@bot.message_handler(commands=['broadcast'])
def bcast(m):
    if m.from_user.id != OWNER_ID: return
    msg = m.text.replace("/broadcast ", "").strip()
    if not msg: return bot.reply_to(m, "Usage: /broadcast MESSAGE")
    con = sqlite3.connect(DB_PATH); c = con.cursor()
    c.execute("SELECT uid FROM users"); uids = [r[0] for r in c.fetchall()]; con.close()
    sent = fail = 0
    for u in uids:
        try: bot.send_message(u, f"📢 <b>ANNOUNCEMENT</b>\n\n{msg}"); sent += 1; time.sleep(0.05)
        except: fail += 1
    bot.reply_to(m, f"✅ Sent: {sent} | ❌ Failed: {fail}")

# ═══════════════ MAIN ═══════════════
if __name__ == "__main__":
    db_init()
    print("⚡ SIMRAN HOSTING v4.0 starting...")
    threading.Thread(target=crash_watchdog, daemon=True).start()
    threading.Thread(target=pending_cleanup, daemon=True).start()
    print("🩺 Watchdog + Cleanup started")
    for d in os.listdir(HOST_DIR):
        bd = os.path.join(HOST_DIR, d)
        if os.path.isdir(bd) and os.path.exists(os.path.join(bd, "info.txt")):
            p = spawn_bot(d)
            if p: RUNNING_BOTS[d] = {"proc": p, "dir": bd}; print(f"✅ Resumed {d}")
    try: bot.remove_webhook()
    except: pass
    print("✅ Ready")
    bot.infinity_polling(timeout=25, long_polling_timeout=20)