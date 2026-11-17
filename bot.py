import logging
import asyncio
import json
import aiohttp
import os
import sys
import time
import gc
import threading

# Low-memory garbage collector optimization
gc.enable()
gc.set_threshold(200, 10, 10)

import replenish_tokens
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from byte import encrypt_api, Encrypt_ID

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Token & Admins
BOT_TOKEN = "9154373382:AAFwxP027lnlTOXztmUrvcWW-vZAXP2Ik1o"
ADMIN_IDS = [8755911692]

# Server Switch Status
SERVER_STATUS = {
    "IND": True,
    "BD": True
}

import datetime

# Concurrency & Cooldown
MAX_CONCURRENT_BOOST_TASKS = 2
BOOST_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_BOOST_TASKS)
ACTIVE_BOOSTS = 0
USER_COOLDOWNS = {}
COOLDOWN_SECONDS = 30  # Optimized user cooldown

UID_COOLDOWNS = {}
UID_COOLDOWN_SECONDS = 60  # Prevents duplicate spam on same FF UID

# User Tracking for Broadcast & Community Analytics
USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

def load_users_data():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            migrated = {}
            for uid in data:
                migrated[str(uid)] = {
                    "id": uid,
                    "name": "Member",
                    "username": "N/A",
                    "joined_at": int(time.time()),
                    "total_boosts": 0,
                    "last_active": int(time.time())
                }
            return migrated
        elif isinstance(data, dict):
            return data
    except Exception as e:
        logger.error(f"Error loading users: {e}")
    return {}

def save_users_data(data):
    try:
        tmp = USERS_FILE + f".{os.getpid()}_{int(time.time()*1000)}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, USERS_FILE)
    except Exception as e:
        logger.error(f"Error saving users: {e}")

async def register_user_rich(user, context=None):
    if not user:
        return False
    user_id = user.id
    users = load_users_data()
    uid_str = str(user_id)
    now = int(time.time())

    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Player"
    username = f"@{user.username}" if user.username else "No Username"

    is_new = uid_str not in users

    if is_new:
        users[uid_str] = {
            "id": user_id,
            "name": full_name,
            "username": username,
            "joined_at": now,
            "total_boosts": 0,
            "last_active": now
        }
        save_users_data(users)
        logger.info(f"🆕 NEW USER JOINED: {full_name} ({username}) [ID: {user_id}]")

        # Real-time alert to Bot Admins with user details
        if context:
            join_dt = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
            alert_text = (
                "🔔 **NEW USER STARTED CODEX BOT!** 👤\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📛 **Name:** `{full_name}`\n"
                f"🏷️ **Username:** {username}\n"
                f"🆔 **Telegram ID:** `{user_id}`\n"
                f"📅 **Joined At:** `{join_dt}`\n"
                f"👥 **Total Registered Members:** `{len(users)}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="Markdown")
                except Exception:
                    pass
    else:
        users[uid_str]["name"] = full_name
        users[uid_str]["username"] = username
        users[uid_str]["last_active"] = now
        save_users_data(users)

    return is_new

def increment_user_boosts(user_id):
    users = load_users_data()
    uid_str = str(user_id)
    if uid_str in users:
        users[uid_str]["total_boosts"] = users[uid_str].get("total_boosts", 0) + 1
        users[uid_str]["last_active"] = int(time.time())
        save_users_data(users)

def register_user(user_id):
    # Lightweight wrapper for backward compatibility
    users = load_users_data()
    uid_str = str(user_id)
    if uid_str not in users:
        users[uid_str] = {
            "id": user_id,
            "name": "Member",
            "username": "N/A",
            "joined_at": int(time.time()),
            "total_boosts": 0,
            "last_active": int(time.time())
        }
        save_users_data(users)

def get_all_users():
    users = load_users_data()
    return [int(uid) for uid in users.keys()]

def check_user_cooldown(user_id, update_timestamp=True):
    if user_id in ADMIN_IDS:
        return True, 0
    now = time.time()
    last_time = USER_COOLDOWNS.get(user_id, 0)
    if now - last_time < COOLDOWN_SECONDS:
        rem = max(1, int(COOLDOWN_SECONDS - (now - last_time)))
        return False, rem
    if update_timestamp:
        USER_COOLDOWNS[user_id] = now
    return True, 0

def check_uid_cooldown(uid, update_timestamp=True):
    now = time.time()
    last_time = UID_COOLDOWNS.get(str(uid), 0)
    if now - last_time < UID_COOLDOWN_SECONDS:
        rem = max(1, int(UID_COOLDOWN_SECONDS - (now - last_time)))
        return False, rem
    if update_timestamp:
        UID_COOLDOWNS[str(uid)] = now
    return True, 0

# Conversation states
SELECT_SERVER, ENTER_UID = range(2)

def get_welcome_keyboard():
    buttons = []
    # Server Selection Buttons
    if SERVER_STATUS.get("IND", True):
        buttons.append([InlineKeyboardButton("🇮🇳 INDIA SERVER — [1K Visits]", callback_data="server_IND")])
    if SERVER_STATUS.get("BD", True):
        buttons.append([InlineKeyboardButton("🇧🇩 BANGLADESH SERVER — [1K Visits]", callback_data="server_BD")])
    if not buttons:
        buttons.append([InlineKeyboardButton("⚠️ Servers Under Maintenance", callback_data="none")])
    
    # Secondary Helper Buttons
    buttons.append([
        InlineKeyboardButton("📊 Live Stock Status", callback_data="menu_status"),
        InlineKeyboardButton("❓ Help & Commands", callback_data="menu_help")
    ])
    return InlineKeyboardMarkup(buttons)

def get_completion_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Boost Another Account", callback_data="action_restart"),
        ],
        [
            InlineKeyboardButton("❓ Group Commands Guide", callback_data="menu_help"),
            InlineKeyboardButton("🔄 Refresh Main Menu", callback_data="action_start_menu")
        ]
    ])

# ═══════════════ PRODUCTION TOKEN POOL & COOLDOWN MANAGER ═══════════════
class TokenPoolManager:
    def __init__(self):
        self.pools = {}
        self.dead_tokens = set()
        self.cooldown_tokens = {}
        self.lock = asyncio.Lock()
        self.file_lock = threading.Lock()
        self.replenishing = {"IND": False, "BD": False}

    def get_token_file(self, server_name):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if server_name == "IND":
            return os.path.join(base_dir, "token_ind.json")
        return os.path.join(base_dir, "token_bd.json")

    def purge_dead_batch_sync(self, server_name, dead_set):
        with self.file_lock:
            path = self.get_token_file(server_name)
            if not os.path.exists(path):
                return 0
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    return 0

                dead_str_set = {str(t).strip() for t in dead_set if t}
                dead_str_set.update(self.dead_tokens)
                updated = []
                for item in data:
                    tok = (item.get("token") or item.get("jwt") or item.get("access_token")) if isinstance(item, dict) else item
                    if str(tok).strip() not in dead_str_set:
                        updated.append(item)

                if len(updated) != len(data):
                    tmp = path + f".{os.getpid()}_{int(time.time()*1000)}.tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(updated, f, indent=2)
                    for _ in range(5):
                        try:
                            os.replace(tmp, path)
                            break
                        except Exception:
                            time.sleep(0.05)
                    logger.info(f"[{server_name}] 🗑️ PERMANENTLY PURGED {len(data) - len(updated)} dead tokens from disk. Remaining: {len(updated)}")
                return len(updated)
            except Exception as e:
                logger.error(f"Error in purge_dead_batch_sync for {server_name}: {e}")
                return 0

    def purge_token_from_file_sync(self, server_name, dead_token):
        return self.purge_dead_batch_sync(server_name, {dead_token})

    def purge_all_dead_from_file_sync(self, server_name):
        return self.purge_dead_batch_sync(server_name, self.dead_tokens)

    def load_from_file(self, server_name):
        path = self.get_token_file(server_name)
        if not os.path.exists(path):
            return [], path

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            tokens = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        tok = item.get("token") or item.get("jwt") or item.get("access_token")
                        if tok and tok not in ["", "N/A"]:
                            tokens.append(str(tok).strip())
                    elif isinstance(item, str) and item.strip():
                        tokens.append(item.strip())
            # Permanent dead token filtration
            active = [t for t in tokens if t not in self.dead_tokens]
            return active, path
        except Exception as e:
            logger.error(f"Error loading tokens for {server_name}: {e}")
            return [], path

    async def get_active_tokens(self, server_name):
        async with self.lock:
            now = time.time()
            self.cooldown_tokens = {t: exp for t, exp in self.cooldown_tokens.items() if exp > now}

            tokens, path = self.load_from_file(server_name)
            self.pools[server_name] = tokens
            available = [t for t in tokens if t not in self.cooldown_tokens]
            return list(available), path

    async def mark_cooldown_429(self, token):
        async with self.lock:
            self.cooldown_tokens[token] = time.time() + 15

    async def mark_dead_permanent(self, server_name, dead_token):
        async with self.lock:
            self.dead_tokens.add(dead_token)
            if server_name in self.pools and dead_token in self.pools[server_name]:
                self.pools[server_name].remove(dead_token)
                logger.warning(f"[{server_name}] ⚠️ Removed dead token from RAM. Remaining: {len(self.pools[server_name])}")

        # Purge immediately from disk file so it NEVER reloads!
        await asyncio.to_thread(self.purge_dead_batch_sync, server_name, {dead_token})

    async def replenish_stock(self, server_name, count=50, status_msg=None):
        try:
            self.replenishing[server_name] = True
            workers = 6 if server_name == "IND" else 3
            logger.info(f"[{server_name}] Generating {count} fresh accounts in-process ({workers} threads)...")

            tot = await asyncio.to_thread(replenish_tokens.generate_batch_sync, count, server_name, workers)

            async with self.lock:
                fresh, _ = self.load_from_file(server_name)
                self.pools[server_name] = fresh

            gc.collect()

            if status_msg:
                try:
                    await status_msg.edit_text(
                        f"🎉 **GENERATION COMPLETED!** 🎉\n\n"
                        f"🌐 **Server:** `{server_name}`\n"
                        f"✅ **Total New Added:** `{count}` IDs\n"
                        f"📈 **Current Total Active Stock:** `{len(fresh)}` IDs\n"
                        f"✨ **Status:** All tokens live in RAM & saved to disk!",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error replenishing {server_name}: {e}")
            if status_msg:
                try:
                    await status_msg.edit_text(f"❌ Error during generation: {e}")
                except Exception:
                    pass
        finally:
            self.replenishing[server_name] = False

POOL_MANAGER = TokenPoolManager()

# ═══════════════ 24/7 DUAL AUTO-GENERATOR STATE & ENGINE ═══════════════
SENTINEL_STATE = {
    "enabled": True,
    "IND": {
        "status": "🟢 Initializing (6 Threads)...",
        "total_generated": 0,
        "batch_start_time": time.time(),
        "avg_sec_per_id": 0.0,
        "threads": 6,
    },
    "BD": {
        "status": "🟢 Initializing (3 Threads)...",
        "total_generated": 0,
        "batch_start_time": time.time(),
        "avg_sec_per_id": 0.0,
        "threads": 3,
    },
    "started_at": time.time(),
}

async def background_sentinel_ind():
    logger.info("[24/7 IND Sentinel] Starting 24/7 India Generator with DOUBLE THREADS (6 Workers)...")
    while True:
        if not SENTINEL_STATE["enabled"]:
            SENTINEL_STATE["IND"]["status"] = "🔴 Paused"
            await asyncio.sleep(5)
            continue

        SENTINEL_STATE["IND"]["status"] = "⚡ Generating (6 Threads)"
        SENTINEL_STATE["IND"]["batch_start_time"] = time.time()
        try:
            # 6 worker threads (double threads for India)
            tot = await asyncio.to_thread(replenish_tokens.generate_batch_sync, 25, "IND", 6)
            await POOL_MANAGER.get_active_tokens("IND")
            SENTINEL_STATE["IND"]["total_generated"] += 25
            elapsed = time.time() - SENTINEL_STATE["IND"]["batch_start_time"]
            if elapsed > 0:
                SENTINEL_STATE["IND"]["avg_sec_per_id"] = round(elapsed / 25, 2)
            if SENTINEL_STATE["enabled"]:
                SENTINEL_STATE["IND"]["status"] = f"🟢 Live ({tot} in stock)"
            gc.collect()
        except Exception as e:
            logger.error(f"[24/7 IND Sentinel] Error: {e}")
            SENTINEL_STATE["IND"]["status"] = f"⚠️ Retry ({str(e)[:15]})"

        await asyncio.sleep(3)

async def background_sentinel_bd():
    logger.info("[24/7 BD Sentinel] Starting 24/7 Bangladesh Generator with Dedicated Threads (3 Workers)...")
    while True:
        if not SENTINEL_STATE["enabled"]:
            SENTINEL_STATE["BD"]["status"] = "🔴 Paused"
            await asyncio.sleep(5)
            continue

        SENTINEL_STATE["BD"]["status"] = "⚡ Generating (3 Threads)"
        SENTINEL_STATE["BD"]["batch_start_time"] = time.time()
        try:
            # 3 dedicated worker threads for BD
            tot = await asyncio.to_thread(replenish_tokens.generate_batch_sync, 25, "BD", 3)
            await POOL_MANAGER.get_active_tokens("BD")
            SENTINEL_STATE["BD"]["total_generated"] += 25
            elapsed = time.time() - SENTINEL_STATE["BD"]["batch_start_time"]
            if elapsed > 0:
                SENTINEL_STATE["BD"]["avg_sec_per_id"] = round(elapsed / 25, 2)
            if SENTINEL_STATE["enabled"]:
                SENTINEL_STATE["BD"]["status"] = f"🟢 Live ({tot} in stock)"
            gc.collect()
        except Exception as e:
            logger.error(f"[24/7 BD Sentinel] Error: {e}")
            SENTINEL_STATE["BD"]["status"] = f"⚠️ Retry ({str(e)[:15]})"

        await asyncio.sleep(3)

import visit_count_pb2

def parse_player_profile(raw_bytes):
    if not raw_bytes:
        return None
    profile = {
        "nickname": None,
        "level": None,
        "likes": None,
        "region": None,
        "bio": None
    }
    try:
        info = visit_count_pb2.Info()
        info.ParseFromString(raw_bytes)
        if info.AccountInfo:
            if info.AccountInfo.PlayerNickname:
                profile["nickname"] = str(info.AccountInfo.PlayerNickname)
            if info.AccountInfo.Levels:
                profile["level"] = int(info.AccountInfo.Levels)
            if info.AccountInfo.Likes:
                profile["likes"] = int(info.AccountInfo.Likes)
            if info.AccountInfo.PlayerRegion:
                profile["region"] = str(info.AccountInfo.PlayerRegion)
    except Exception as e:
        logger.debug(f"Protobuf info parse exception: {e}")

    # Extract Bio/Signature from raw wire bytes
    try:
        i = 0
        strings_found = []
        while i < len(raw_bytes):
            key = 0
            shift = 0
            while i < len(raw_bytes):
                b = raw_bytes[i]
                i += 1
                key |= (b & 0x7f) << shift
                if not (b & 0x80):
                    break
                shift += 7
            tag = key >> 3
            wire = key & 0x07
            if wire == 2:
                length = 0
                shift = 0
                while i < len(raw_bytes):
                    b = raw_bytes[i]
                    i += 1
                    length |= (b & 0x7f) << shift
                    if not (b & 0x80):
                        break
                    shift += 7
                chunk = raw_bytes[i:i+length]
                i += length
                try:
                    s = chunk.decode("utf-8").strip()
                    if s and len(s) >= 2 and all(c.isprintable() or c.isspace() for c in s):
                        strings_found.append(s)
                except Exception:
                    pass
            elif wire == 0:
                while i < len(raw_bytes):
                    b = raw_bytes[i]
                    i += 1
                    if not (b & 0x80):
                        break
            elif wire == 1:
                i += 8
            elif wire == 5:
                i += 4
            else:
                break

        nick = profile.get("nickname") or ""
        reg = profile.get("region") or ""
        for s in strings_found:
            if s != nick and s != reg and not s.isdigit() and len(s) > 1:
                profile["bio"] = s
                break
    except Exception:
        pass

    if not profile.get("bio"):
        profile["bio"] = "No Bio / Default"

    return profile

def get_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    return "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"

async def visit(session, url, token, uid, data):
    headers = {
        "ReleaseVersion": "OB55",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False, timeout=aiohttp.ClientTimeout(total=4)) as resp:
            if resp.status == 200:
                raw_bytes = await resp.read()
                return "SUCCESS", raw_bytes, token
            elif resp.status in (401, 403):
                return "DEAD_TOKEN", None, token
            elif resp.status == 429:
                return "RATE_LIMITED", None, token
            return "FAIL", None, token
    except Exception:
        return "ERROR", None, token

# --- BACKGROUND WORKER FOR 1K VISITS ---

async def process_visit_task(status_msg, uid, server, tokens, token_file):
    global ACTIVE_BOOSTS
    TARGET_VISITS = 1000
    start_time = time.time()
    player_profile = None

    try:
        async with BOOST_SEMAPHORE:
            ACTIVE_BOOSTS += 1
            url = get_url(server)
            connector = aiohttp.TCPConnector(limit=80, limit_per_host=80, ttl_dns_cache=300, enable_cleanup_closed=True)
            total_success = 0
            total_sent = 0
            BATCH_SIZE = 80
            token_index = 0
            last_ui_edit = time.time()
            consecutive_fails = 0

            async with aiohttp.ClientSession(connector=connector) as session:
                data = bytes.fromhex(encrypt_api("08" + Encrypt_ID(str(uid)) + "1801"))

                while total_success < TARGET_VISITS:
                    active_tokens, _ = await POOL_MANAGER.get_active_tokens(server)
                    if not active_tokens:
                        try:
                            await status_msg.edit_text(
                                f"⚠️ **OUT OF STOCK — WAIT FOR NEW STOCKS** ⚠️\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"👤 **Player UID:** `{uid}`\n"
                                f"🌐 **Server:** `{server}`\n"
                                f"📊 **Delivered:** `{total_success}/1000` visits\n\n"
                                f"🛑 *Is samay valid IDs stock mein nahi hain!*\n"
                                f"⏳ *Process ko yahin rok diya gaya hai. Kripya naye stock add hone ka intezaar karein (Wait for new stocks).*",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass
                        return

                    current_batch = min(BATCH_SIZE, TARGET_VISITS - total_success)
                    batch_tokens = []
                    for _ in range(current_batch):
                        batch_tokens.append(active_tokens[token_index % len(active_tokens)])
                        token_index += 1

                    tasks = [
                        asyncio.create_task(visit(session, url, tok, uid, data))
                        for tok in batch_tokens
                    ]
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    batch_success = 0
                    dead_in_batch = set()
                    for res in results:
                        if isinstance(res, tuple) and len(res) == 3:
                            status, raw_bytes, tok = res
                            if status == "SUCCESS":
                                batch_success += 1
                                if player_profile is None and raw_bytes:
                                    player_profile = parse_player_profile(raw_bytes)
                            elif status == "DEAD_TOKEN":
                                dead_in_batch.add(tok)
                            elif status == "RATE_LIMITED":
                                pass

                    if dead_in_batch:
                        for d_tok in dead_in_batch:
                            POOL_MANAGER.dead_tokens.add(d_tok)
                        asyncio.create_task(asyncio.to_thread(POOL_MANAGER.purge_dead_batch_sync, server, dead_in_batch))

                    if batch_success == 0:
                        consecutive_fails += 1
                    else:
                        consecutive_fails = 0

                    if consecutive_fails >= 3:
                        logger.warning(f"Visit task aborted: {consecutive_fails} consecutive failed batches.")
                        try:
                            await status_msg.edit_text(
                                f"⚠️ **VISIT TASK STOPPED — OUT OF STOCK / RATE LIMITED** ⚠️\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"👤 **Player UID:** `{uid}`\n"
                                f"🌐 **Server:** `{server}`\n"
                                f"📊 **Delivered:** `{total_success}/1000` visits\n\n"
                                f"❌ **Stock IDs temporary block ya exhaust ho chuki hain!**\n"
                                f"🛑 *Lagataar requests fail hone ke kaaran task yahin rok diya gaya hai.*\n"
                                f"⏳ *Kripya 24/7 background generator dwara fresh IDs stock aane ka intezaar karein.*",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass
                        return

                    total_success += batch_success
                    total_sent += current_batch

                    if time.time() - last_ui_edit > 2.0 or total_success >= TARGET_VISITS:
                        last_ui_edit = time.time()
                        elapsed = int(time.time() - start_time)
                        progress_pct = int((total_success / TARGET_VISITS) * 100)
                        filled_blocks = int(progress_pct / 10)
                        bar = "▓" * filled_blocks + "░" * (10 - filled_blocks)
                        
                        profile_info_str = ""
                        if player_profile and player_profile.get("nickname"):
                            p_name = player_profile.get("nickname", "Player")
                            p_lvl = player_profile.get("level", 0)
                            p_likes = player_profile.get("likes", 0)
                            p_bio = player_profile.get("bio", "No Bio")
                            profile_info_str = (
                                f"🎮 **Player Profile Found:**\n"
                                f"• **IGN:** `{p_name}` (Lv. `{p_lvl}`)\n"
                                f"• **Likes:** `{p_likes}` | **Bio:** `{p_bio}`\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            )
                        try:
                            await status_msg.edit_text(
                                f"🚀 **CODEX - 1,000 VISITS IN PROGRESS...**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"👤 **Player UID:** `{uid}`\n"
                                f"🌐 **Server:** `{server}`\n"
                                f"{profile_info_str}"
                                f"🎯 **Target:** `1,000 Visits`\n"
                                f"✅ **Delivered:** `{total_success}/1000` ({progress_pct}%)\n"
                                f"📊 **Progress:** `[{bar}]`\n"
                                f"⏱️ **Elapsed:** `{elapsed}s`\n"
                                f"🔑 **Active Stock:** `{len(active_tokens)}` IDs in RAM\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"⚡ *Delivering real-time profile views safely...*",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass

                    await asyncio.sleep(0.04)

            total_elapsed = round(time.time() - start_time, 1)
            p_name = player_profile.get("nickname", "Player") if player_profile else "Player"
            p_lvl = player_profile.get("level", 0) if player_profile else "N/A"
            p_likes = player_profile.get("likes", 0) if player_profile else "N/A"
            p_bio = player_profile.get("bio", "No Bio / Default") if player_profile else "Default Bio"
            p_reg = player_profile.get("region", server) if player_profile else server

            completion_text = (
                f"🎉 **MISSION SUCCESS - CODEX 1,000 VISITS!** 🎉\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎮 **TARGET PLAYER PROFILE INFO:**\n"
                f"• 👤 **In-Game Name:** `{p_name}`\n"
                f"• 🆔 **Player UID:** `{uid}`\n"
                f"• ⭐ **Level:** `{p_lvl}`\n"
                f"• ❤️ **Current Likes:** `{p_likes}`\n"
                f"• 🌐 **Server Region:** `{p_reg}`\n"
                f"• 📝 **Bio / Signature:** `{p_bio}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 **BOOST DELIVERY STATS:**\n"
                f"• ✅ **Visits Delivered:** `{total_success}`\n"
                f"• ⚡ **Packets Sent:** `{total_sent}`\n"
                f"• ⏱️ **Time Taken:** `{total_elapsed}s`\n"
                f"• 🛡️ **Status:** 100% Anti-Ban Safe & Verified\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👑 **Bot Owner:** Smruti\n"
                f"💬 **Need Help?** Type `/help` for support!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✨ *Open Free Fire now to see your updated profile views!*\n\n"
                f"👇 **Choose an action below:**"
            )

            success_card = os.path.join(os.path.dirname(os.path.abspath(__file__)), "success.jpg")
            photo_sent = False
            if os.path.exists(success_card):
                try:
                    with open(success_card, "rb") as sf:
                        await status_msg.reply_photo(
                            photo=sf,
                            caption=completion_text,
                            reply_markup=get_completion_keyboard(),
                            parse_mode="Markdown"
                        )
                    photo_sent = True
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                except Exception as pe:
                    logger.warning(f"Could not send victory photo: {pe}")

            if not photo_sent:
                try:
                    await status_msg.edit_text(completion_text, reply_markup=get_completion_keyboard(), parse_mode="Markdown")
                except Exception:
                    pass
            gc.collect()
    except Exception as e:
        logger.exception(f"Error in process_visit_task: {e}")
    finally:
        ACTIVE_BOOSTS = max(0, ACTIVE_BOOSTS - 1)


# ═══════════════ DIRECT GROUP COMMAND: /visit <region> <uid> ═══════════════

async def handle_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    await register_user_rich(user, context)
    allowed, rem = check_user_cooldown(user_id, update_timestamp=True)
    if not allowed:
        await update.message.reply_text(
            f"⏳ **Cooldown Active:** Please wait `{rem}`s before sending another request.",
            parse_mode="Markdown"
        )
        return

    args = context.args
    if not args or len(args) < 2:
        if update.effective_chat.type == "private":
            return await start(update, context)
        else:
            await update.message.reply_text(
                "ℹ️ **Format:** `/visit <SERVER> <UID>`\n\n**Example:**\n`/visit IND 19137608188`\n`/visit BD 19137608188`\n\nYeh command direct **1K Visits** boost karta hai!",
                parse_mode="Markdown"
            )
            return

    server = args[0].upper().strip()
    uid_str = args[1].strip()

    if server not in ["IND", "BD"]:
        await update.message.reply_text("❌ Server sirf `IND` ya `BD` hona chahiye.", parse_mode="Markdown")
        return

    if not SERVER_STATUS.get(server, True):
        await update.message.reply_text(f"⚠️ **Server {server} is temporarily maintenance/OFF.**", parse_mode="Markdown")
        return

    if not uid_str.isdigit():
        await update.message.reply_text("❌ UID sirf numbers mein hona chahiye.", parse_mode="Markdown")
        return

    uid = int(uid_str)
    uid_allowed, uid_rem = check_uid_cooldown(uid, update_timestamp=True)
    if not uid_allowed:
        await update.message.reply_text(
            f"⏳ **UID Cooldown Active:** Is UID `{uid}` par abhi-abhi boost bheja gaya hai.\n"
            f"Kripya `{uid_rem}`s wait karein taaki Free Fire server visits ko discard na kare!",
            parse_mode="Markdown"
        )
        return

    if not uid_str.isdigit():
        await update.message.reply_text("❌ UID sirf numbers me honi chahiye!", parse_mode="Markdown")
        return

    uid = int(uid_str)
    tokens, token_file = await POOL_MANAGER.get_active_tokens(server)

    if not tokens:
        await update.message.reply_text(f"⚠️ **OUT OF STOCK!** Server `{server}` ke liye abhi valid IDs stock mein nahi hain. Kripya naye stock add hone ka intezaar karein (**Wait for new stocks**).", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(
        f"🚀 **CODEX - Group Request Received!**\n\n"
        f"🆔 **UID:** `{uid}`\n"
        f"🌐 **Server:** `{server}`\n"
        f"⚡ **Target Visits:** `1,000 (1K)`\n"
        f"🔑 **Tokens Ready:** `{len(tokens)}` IDs in RAM\n\n"
        "Sending 1K visits now...",
        parse_mode="Markdown"
    )

    asyncio.create_task(process_visit_task(status_msg, uid, server, tokens, token_file))


# ═══════════════ ADMIN CONTROL PANEL & BROADCAST ═══════════════

def make_progress_bar(count, max_val=200):
    pct = min(100, int((count / max_val) * 100))
    filled = min(10, max(0, int((count / max_val) * 10)))
    return f"[{'█' * filled}{'░' * (10 - filled)}] {pct}%"

def format_admin_text(ind_count, bd_count):
    sentinel_en = SENTINEL_STATE["enabled"]
    is_running_icon = "🟢 ACTIVE (24/7 DUAL RUNNING)" if sentinel_en else "🔴 STOPPED (PAUSED)"

    ind_data = SENTINEL_STATE["IND"]
    bd_data = SENTINEL_STATE["BD"]

    ind_speed = ind_data["avg_sec_per_id"]
    ind_speed_txt = f"~{ind_speed}s/ID" if ind_speed > 0 else "Calibrating..."
    if ind_speed > 0:
        ind_speed_txt += f" (~{round(60/ind_speed, 1)} IDs/min)"

    bd_speed = bd_data["avg_sec_per_id"]
    bd_speed_txt = f"~{bd_speed}s/ID" if bd_speed > 0 else "Calibrating..."
    if bd_speed > 0:
        bd_speed_txt += f" (~{round(60/bd_speed, 1)} IDs/min)"

    tot_session = ind_data["total_generated"] + bd_data["total_generated"]
    total_users = len(get_all_users())
    dead_purged = len(POOL_MANAGER.dead_tokens)

    bar_ind = make_progress_bar(ind_count, 200)
    bar_bd = make_progress_bar(bd_count, 200)

    return (
        "👑 **CODEX VISIT BOOSTER - LIVE ADMIN PANEL** 👑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 **Real-Time Token Stock:**\n"
        f"• 🇮🇳 **IND Server:** `{ind_count}` Active IDs {bar_ind} ({'🟢 Active' if SERVER_STATUS['IND'] else '🔴 Off'})\n"
        f"• 🇧🇩 **BD Server:** `{bd_count}` Active IDs {bar_bd} ({'🟢 Active' if SERVER_STATUS['BD'] else '🔴 Off'})\n"
        f"• 🗑️ **Revoked / Purged IDs:** `{dead_purged}` removed permanently\n\n"
        "⚙️ **Dual 24/7 Auto-Generator Monitors:**\n"
        f"• **Generator Engine:** {is_running_icon}\n"
        f"• 🇮🇳 **IND Generator (6x Threads - 2x Speed):** `{ind_data['status']}`\n"
        f"  └ Speed: `{ind_speed_txt}` | Total Added: `{ind_data['total_generated']}` IDs\n"
        f"• 🇧🇩 **BD Generator (3x Threads Dedicated):** `{bd_data['status']}`\n"
        f"  └ Speed: `{bd_speed_txt}` | Total Added: `{bd_data['total_generated']}` IDs\n"
        f"• 📈 **Total Session Generated:** `{tot_session}` IDs\n\n"
        "👥 **Live System & Users:**\n"
        f"• **Active Concurrent Boosts:** `{ACTIVE_BOOSTS}` visits running\n"
        f"• **Total Registered Users:** `{total_users}` players\n"
        f"• **Global Cooldown:** `10s` (Anti-Spam active)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **Admin Controls:** Niche diye buttons se manage karein:"
    )

def get_admin_keyboard():
    ind_st = "🟢 ON" if SERVER_STATUS.get("IND", True) else "🔴 OFF"
    bd_st = "🟢 ON" if SERVER_STATUS.get("BD", True) else "🔴 OFF"
    sentinel_btn = "⏹️ Stop 24/7 Generator" if SENTINEL_STATE["enabled"] else "▶️ Start 24/7 Generator"
    users_count = len(get_all_users())
    keyboard = [
        [
            InlineKeyboardButton(sentinel_btn, callback_data="admin_toggle_sentinel"),
        ],
        [
            InlineKeyboardButton("➕ Add 50 IND IDs", callback_data="admin_refill_IND"),
            InlineKeyboardButton("➕ Add 50 BD IDs", callback_data="admin_refill_BD"),
        ],
        [
            InlineKeyboardButton(f"IND Server: {ind_st}", callback_data="admin_toggle_IND"),
            InlineKeyboardButton(f"BD Server: {bd_st}", callback_data="admin_toggle_BD"),
        ],
        [
            InlineKeyboardButton(f"👥 Users: {users_count}", callback_data="admin_users"),
            InlineKeyboardButton("📢 Send Broadcast", callback_data="admin_broadcast_info"),
        ],
        [
            InlineKeyboardButton("🧹 Reset User Cooldowns", callback_data="admin_clear_cooldowns"),
            InlineKeyboardButton("🗑️ Clear Dead Tokens", callback_data="admin_clear_dead"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh Real-Time Status", callback_data="admin_refresh"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ **Access Denied:** Yeh command sirf Bot Admin ke liye hai.")
        return

    ind_tokens, _ = await POOL_MANAGER.get_active_tokens("IND")
    bd_tokens, _ = await POOL_MANAGER.get_active_tokens("BD")
    text = format_admin_text(len(ind_tokens), len(bd_tokens))
    await update.message.reply_text(text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ **Access Denied:** Yeh command sirf Bot Admin ke liye hai.")
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "📢 **Broadcast Usage:**\n`/broadcast <Aapka Message>`\n\n*Yeh message bot ke sabhi users ko turant bhej diya jayega!*",
            parse_mode="Markdown"
        )
        return

    users = get_all_users()
    if not users:
        await update.message.reply_text("❌ Abhi koi registered users nahi hain.")
        return

    status_msg = await update.message.reply_text(f"🚀 **Broadcasting announcement to {len(users)} users...**")
    success_count = 0
    fail_count = 0

    for uid in users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 **CODEX OFFICIAL ANNOUNCEMENT** 📢\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n{text}\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n⚡ *CODEX Visit Booster Team*",
                parse_mode="Markdown"
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    await status_msg.edit_text(
        f"✅ **BROADCAST COMPLETED!**\n\n"
        f"👥 **Total Target Users:** `{len(users)}`\n"
        f"✅ **Successfully Delivered:** `{success_count}`\n"
        f"❌ **Failed / Blocked:** `{fail_count}`",
        parse_mode="Markdown"
    )

def format_user_directory_text(page=0, per_page=5):
    users = load_users_data()
    user_list = list(users.values())
    user_list.sort(key=lambda x: x.get("joined_at", 0), reverse=True)

    total = len(user_list)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * per_page
    end_idx = min(start_idx + per_page, total)
    current_slice = user_list[start_idx:end_idx]

    lines = [
        "👥 **CODEX USER DATABASE & ID DIRECTORY** 👥",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 **Total Registered Members:** `{total}` | **Page:** `{page + 1}/{total_pages}`\n"
    ]

    if not current_slice:
        lines.append("❌ Abhi koi users registered nahi hain.")
    else:
        for idx, u in enumerate(current_slice, start=start_idx + 1):
            join_dt = datetime.datetime.fromtimestamp(u.get("joined_at", time.time())).strftime("%d %b, %H:%M")
            lines.append(
                f"{idx}. 👤 **{u.get('name', 'Player')}** ({u.get('username', 'N/A')})\n"
                f"   ├ 🆔 **Telegram ID:** `{u.get('id')}`\n"
                f"   ├ 📅 **Joined:** `{join_dt}`\n"
                f"   └ 🚀 **Boosts Used:** `{u.get('total_boosts', 0)}` times\n"
            )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 *Tip: Kisi specific user ki info ke liye type karein: `/user <ID>`*")
    return "\n".join(lines), page, total_pages

def get_user_directory_keyboard(page, total_pages):
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_users_page_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="admin_users_noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_users_page_{page+1}"))

    keyboard = [
        nav_row,
        [
            InlineKeyboardButton("🔄 Refresh Directory", callback_data=f"admin_users_page_{page}"),
            InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_refresh"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ **Access Denied:** Yeh command sirf Bot Admin ke liye hai.")
        return

    if not context.args:
        await update.message.reply_text("ℹ️ **Usage:** `/user <TELEGRAM_USER_ID>`\nExample: `/user 8923505721`", parse_mode="Markdown")
        return

    target_id = context.args[0].strip()
    users = load_users_data()
    u = users.get(target_id)
    if not u:
        await update.message.reply_text(f"❌ User ID `{target_id}` database mein nahi mila.", parse_mode="Markdown")
        return

    join_dt = datetime.datetime.fromtimestamp(u.get("joined_at", time.time())).strftime("%Y-%m-%d %H:%M:%S")
    last_dt = datetime.datetime.fromtimestamp(u.get("last_active", time.time())).strftime("%Y-%m-%d %H:%M:%S")

    info_text = (
        "👤 **CODEX USER PROFILE INSPECTOR** 👤\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Telegram ID:** `{u.get('id')}`\n"
        f"📛 **Full Name:** `{u.get('name')}`\n"
        f"🏷️ **Username:** {u.get('username')}\n"
        f"📅 **Registered Date:** `{join_dt}`\n"
        f"⏰ **Last Active:** `{last_dt}`\n"
        f"🚀 **Total Boosts Done:** `{u.get('total_boosts', 0)}` times\n"
        f"🛡️ **Status:** 🟢 Active Member\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(info_text, parse_mode="Markdown")

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("Access Denied", show_alert=True)
        return

    data = query.data
    await query.answer()

    if data == "admin_refresh":
        ind_tokens, _ = await POOL_MANAGER.get_active_tokens("IND")
        bd_tokens, _ = await POOL_MANAGER.get_active_tokens("BD")
        text = format_admin_text(len(ind_tokens), len(bd_tokens))
        try:
            await query.edit_message_text(text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        except Exception:
            pass

    elif data == "admin_toggle_sentinel":
        SENTINEL_STATE["enabled"] = not SENTINEL_STATE["enabled"]
        if not SENTINEL_STATE["enabled"]:
            SENTINEL_STATE["IND"]["status"] = "🔴 Paused"
            SENTINEL_STATE["BD"]["status"] = "🔴 Paused"
        else:
            SENTINEL_STATE["IND"]["status"] = "🟢 Starting (6 Threads)..."
            SENTINEL_STATE["BD"]["status"] = "🟢 Starting (3 Threads)..."

        ind_tokens, _ = await POOL_MANAGER.get_active_tokens("IND")
        bd_tokens, _ = await POOL_MANAGER.get_active_tokens("BD")
        text = format_admin_text(len(ind_tokens), len(bd_tokens))
        try:
            await query.edit_message_text(text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        except Exception:
            pass

    elif data.startswith("admin_toggle_"):
        srv = data.replace("admin_toggle_", "")
        SERVER_STATUS[srv] = not SERVER_STATUS[srv]
        ind_tokens, _ = await POOL_MANAGER.get_active_tokens("IND")
        bd_tokens, _ = await POOL_MANAGER.get_active_tokens("BD")
        text = format_admin_text(len(ind_tokens), len(bd_tokens))
        try:
            await query.edit_message_text(text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        except Exception:
            pass

    elif data.startswith("admin_refill_"):
        srv = data.replace("admin_refill_", "")
        status_msg = await query.message.reply_text(
            f"⚙️ **CODEX - Starting Generation for {srv}...**\n\n"
            f"📊 **Target:** `50` IDs\n"
            f"⏳ Initializing GOJOXGEN..."
        )
        asyncio.create_task(POOL_MANAGER.replenish_stock(srv, 50, status_msg))

    elif data == "admin_clear_cooldowns":
        USER_COOLDOWNS.clear()
        UID_COOLDOWNS.clear()
        await query.answer("✅ Sabhi users & UIDs ke Cooldowns reset kar diye gaye!", show_alert=True)

    elif data == "admin_clear_dead":
        purged_ind = await asyncio.to_thread(POOL_MANAGER.purge_all_dead_from_file_sync, "IND")
        purged_bd = await asyncio.to_thread(POOL_MANAGER.purge_all_dead_from_file_sync, "BD")
        ind_tokens, _ = await POOL_MANAGER.get_active_tokens("IND")
        bd_tokens, _ = await POOL_MANAGER.get_active_tokens("BD")
        await query.answer(f"🗑️ Dead tokens permanently deleted from disk!\nIND: {len(ind_tokens)} | BD: {len(bd_tokens)} remaining.", show_alert=True)
        text = format_admin_text(len(ind_tokens), len(bd_tokens))
        try:
            await query.edit_message_text(text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        except Exception:
            pass

    elif data.startswith("admin_users"):
        if data == "admin_users_noop":
            await query.answer("Page Indicator", show_alert=False)
            return
        page = 0
        if data.startswith("admin_users_page_"):
            try:
                page = int(data.replace("admin_users_page_", ""))
            except Exception:
                page = 0
        text, p, tot_p = format_user_directory_text(page)
        try:
            await query.edit_message_text(text, reply_markup=get_user_directory_keyboard(p, tot_p), parse_mode="Markdown")
        except Exception:
            pass

    elif data == "admin_broadcast_info":
        await query.message.reply_text(
            "📢 **BROADCAST ANNOUNCEMENT GUIDE**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Sabhi registered users ko ek sath message bhejne ke liye type karein:\n\n"
            "`/broadcast <Aapka Announcement>`\n\n"
            "⚡ **Example:**\n"
            "`/broadcast Dosto, stock 500+ fresh IDs se refill ho chuka hai! Abhi boost karein!`",
            parse_mode="Markdown"
        )


# ═══════════════ USER INTERACTIVE PRIVATE CHAT FLOW ═══════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.args and len(context.args) >= 2:
        await handle_direct_command(update, context)
        return ConversationHandler.END

    user = update.effective_user
    await register_user_rich(user, context)
    user_name = user.first_name or "Player"
    user_id = user.id
    username = f"@{user.username}" if user.username else "No Username"

    welcome_text = (
        f"⚡ **WELCOME TO CODEX VISIT BOOSTER BOT** ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Player:** `{user_name}` ({username})\n"
        f"🆔 **Telegram ID:** `{user_id}`\n"
        f"👑 **Owner & Developer:** Smruti\n"
        f"🛡️ **System Status:** 🟢 100% Anti-Ban Safe & Online\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 **CODEX Capabilities:**\n"
        f"• ⚡ **1,000 (1K) Profile Visits** per request\n"
        f"• 🔍 **Live Player Profile Info:** IGN, Level, Likes & Bio\n"
        f"• 🌐 **Servers Supported:** 🇮🇳 India & 🇧🇩 Bangladesh\n"
        f"• 🔒 **Direct Group & Private Commands**\n\n"
        f"📌 **How to Use:**\n"
        f"1️⃣ Niche diye button se apna Server choose karein.\n"
        f"2️⃣ Apna Player UID send karein.\n"
        f"3️⃣ Instant 1,000 visits deliver ho jayengi!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 **Pehle apna Game Server select karein:**"
    )

    # If triggered from an inline button (action_restart or action_start_menu)
    if update.callback_query:
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass
        try:
            await query.edit_message_caption(
                caption=welcome_text,
                reply_markup=get_welcome_keyboard(),
                parse_mode="Markdown"
            )
        except Exception:
            try:
                await query.edit_message_text(
                    welcome_text,
                    reply_markup=get_welcome_keyboard(),
                    parse_mode="Markdown"
                )
            except Exception:
                await query.message.reply_text(
                    welcome_text,
                    reply_markup=get_welcome_keyboard(),
                    parse_mode="Markdown"
                )
        return SELECT_SERVER

    # From /start command
    if update.message:
        banner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banner.jpg")
        photo_sent = False
        if os.path.exists(banner_path):
            try:
                with open(banner_path, "rb") as bf:
                    await update.message.reply_photo(
                        photo=bf,
                        caption=welcome_text,
                        reply_markup=get_welcome_keyboard(),
                        parse_mode="Markdown"
                    )
                photo_sent = True
            except Exception as pe:
                logger.warning(f"Could not send welcome banner: {pe}")

        if not photo_sent:
            await update.message.reply_text(
                welcome_text,
                reply_markup=get_welcome_keyboard(),
                parse_mode="Markdown"
            )

    return SELECT_SERVER

async def menu_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    register_user(update.effective_user.id)

    if data == "menu_help":
        help_text = (
            "📖 **CODEX VISIT BOOSTER — OFFICIAL HELP & SUPPORT** 📖\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👑 **Bot Owner & Developer:** Smruti\n"
            "💬 **Direct Support Desk:** [Contact Smruti](https://t.me/smruti)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💬 **Private Chat Mode:**\n"
            "1. Send `/start`\n"
            "2. Select your server (`🇮🇳 India` or `🇧🇩 Bangladesh`)\n"
            "3. Send your **Player UID**\n"
            "4. Profile info (IGN, Level, Likes & Bio) detect hokar 1,000 visits deliver ho jayengi!\n\n"
            "👥 **Group Mode (Instant Boost):**\n"
            "Bot ko apne group mein add karein aur type karein:\n"
            "• `/visit IND <UID>` (For India)\n"
            "• `/visit BD <UID>` (For Bangladesh)\n\n"
            "⚡ **Example:** `/visit IND 19137608188`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ *100% Anti-Ban Safe & Official Garena Protocol.*"
        )
        await query.message.reply_text(help_text, parse_mode="Markdown")

    elif data == "menu_status":
        ind_tokens, _ = await POOL_MANAGER.get_active_tokens("IND")
        bd_tokens, _ = await POOL_MANAGER.get_active_tokens("BD")
        status_text = (
            "📊 **CODEX SYSTEM LIVE STATUS**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🇮🇳 **India Server:** {'🟢 Online' if SERVER_STATUS['IND'] else '🔴 Maintenance'}\n"
            f"• Stock Ready: `{len(ind_tokens)}` Active IDs\n\n"
            f"🇧🇩 **Bangladesh Server:** {'🟢 Online' if SERVER_STATUS['BD'] else '🔴 Maintenance'}\n"
            f"• Stock Ready: `{len(bd_tokens)}` Active IDs\n\n"
            f"⚡ **Delivery Speed:** ~15-20s per 1K Visits\n"
            f"🛡️ **System Status:** 100% Operational"
        )
        await query.message.reply_text(status_text, parse_mode="Markdown")

async def server_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    register_user(user_id)
    allowed, rem = check_user_cooldown(user_id, update_timestamp=False)
    if not allowed:
        await query.answer(f"⏳ Cooldown Active: Kripya {rem}s intezaar karein!", show_alert=True)
        return SELECT_SERVER
    
    server = query.data.replace("server_", "")
    if not SERVER_STATUS.get(server, True):
        msg = f"⚠️ **Server {server} is currently offline for maintenance.**"
        try:
            await query.edit_message_text(text=msg, parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data['server'] = server
    
    text = (
        f"✅ **Server Selected:** `{server}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👉 Ab apna target **Player UID** send karein:\n"
        f"*(UID bhejte hi direct 1,000 विज़िट्स शुरू हो जाएँगी!)*"
    )
    try:
        await query.edit_message_caption(caption=text, parse_mode="Markdown")
    except Exception:
        try:
            await query.edit_message_text(text=text, parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(text=text, parse_mode="Markdown")
    return ENTER_UID

async def uid_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id
    await register_user_rich(user, context)
    allowed, rem = check_user_cooldown(user_id, update_timestamp=True)
    if not allowed:
        await update.message.reply_text(
            f"⏳ **Cooldown Active:** Kripya `{rem}`s intezaar karein naya boost request bhejne se pehle.",
            parse_mode="Markdown"
        )
        return ENTER_UID

    user_input = update.message.text.strip()
    if not user_input.isdigit():
        await update.message.reply_text("❌ Invalid UID! Numbers only enter karein:")
        return ENTER_UID

    uid = int(user_input)
    uid_allowed, uid_rem = check_uid_cooldown(uid, update_timestamp=True)
    if not uid_allowed:
        await update.message.reply_text(
            f"⏳ **UID Cooldown Active:** Is UID `{uid}` par abhi-abhi boost bheja gaya hai.\n"
            f"Kripya `{uid_rem}`s wait karein taaki Free Fire server visits ko count kare!",
            parse_mode="Markdown"
        )
        return ENTER_UID

    server = context.user_data.get('server', 'IND')

    tokens, token_file = await POOL_MANAGER.get_active_tokens(server)

    if not tokens:
        await update.message.reply_text(
            f"⚠️ **OUT OF STOCK!** Region **{server}** ke liye abhi IDs stock mein nahi hain. Kripya naye stock add hone ka intezaar karein (**Wait for new stocks**).",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    status_msg = await update.message.reply_text(
        f"🚀 **CODEX - Starting 1K Visits Task...**\n\n"
        f"🆔 **Player UID:** `{uid}`\n"
        f"🌐 **Server:** `{server}`\n"
        f"⚡ **Target Visits:** `1,000 (1K)`\n"
        f"🔑 **Tokens Ready in RAM:** `{len(tokens)}` IDs",
        parse_mode="Markdown"
    )

    asyncio.create_task(process_visit_task(status_msg, uid, server, tokens, token_file))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Task cancelled.")
    return ConversationHandler.END

async def post_init(application):
    # Launch dual 24/7 background generators (IND 6x threads, BD 3x threads)
    asyncio.create_task(background_sentinel_ind())
    asyncio.create_task(background_sentinel_bd())

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Admin Panel & Broadcast handlers
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("bc", broadcast_command))
    app.add_handler(CommandHandler("user", user_info_command))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))

    # Direct commands for groups:
    app.add_handler(CommandHandler("visit", handle_direct_command))
    app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text(
        "📖 **CODEX VISIT BOOSTER — HELP & SUPPORT GUIDE** 📖\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👑 **Bot Owner & Developer:** Smruti\n"
        "💬 **Direct Support:** Contact Admin (@smruti)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💬 **Private Chat Mode:**\n"
        "1. Type `/start` in this chat.\n"
        "2. Select your server (`🇮🇳 India` or `🇧🇩 Bangladesh`).\n"
        "3. Send your **Player UID**.\n"
        "4. Aapka profile info (IGN, Level, Likes, Bio) detect hokar 1,000 visits deliver ho jayengi!\n\n"
        "👥 **Group Mode (Instant Boost):**\n"
        "Bot ko apne Telegram group mein add karein aur type karein:\n"
        "• `/visit IND <UID>` (For India)\n"
        "• `/visit BD <UID>` (For Bangladesh)\n\n"
        "⚡ **Example:** `/visit IND 19137608188`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛡️ *100% Anti-Ban Safe & Official Garena Protocol.*",
        parse_mode="Markdown"
    )))

    # General Menu button callbacks:
    app.add_handler(CallbackQueryHandler(menu_callbacks, pattern="^menu_"))

    # Interactive conversation handler with Re-entry for Restart & Refresh:
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(start, pattern="^(action_restart|action_start_menu)$"),
        ],
        states={
            SELECT_SERVER: [
                CallbackQueryHandler(server_selected, pattern="^server_"),
                CallbackQueryHandler(start, pattern="^(action_restart|action_start_menu)$"),
            ],
            ENTER_UID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, uid_received),
                CallbackQueryHandler(start, pattern="^(action_restart|action_start_menu)$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(start, pattern="^(action_restart|action_start_menu)$"),
        ],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    
    print("CODEX BOT is running with Full Admin Suite, Broadcast Engine, and Smooth UI!")
    import threading
    if threading.current_thread() is threading.main_thread():
        app.run_polling()
    else:
        app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
