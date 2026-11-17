import os
import sys
import json
import time
import asyncio
import aiohttp
from flask import Flask, jsonify, request, render_template_string
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_token_file(server_name):
    if server_name == "IND":
        return os.path.join(BASE_DIR, "token_ind.json")
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return os.path.join(BASE_DIR, "token_br.json")
    return os.path.join(BASE_DIR, "token_bd.json")

def load_tokens(server_name):
    path = get_token_file(server_name)
    if not os.path.exists(path):
        return []
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
        return tokens
    except Exception:
        return []

def get_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    # Active Maine Coon host for BD & Global
    return "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"

def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)
        return {
            "uid": info.AccountInfo.UID if info.AccountInfo.UID else 0,
            "nickname": info.AccountInfo.PlayerNickname if info.AccountInfo.PlayerNickname else "Unknown",
            "likes": info.AccountInfo.Likes if info.AccountInfo.Likes else 0,
            "region": info.AccountInfo.PlayerRegion if info.AccountInfo.PlayerRegion else "",
            "level": info.AccountInfo.Levels if info.AccountInfo.Levels else 0
        }
    except Exception:
        return None

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
                raw = await resp.read()
                return True, raw
            return False, None
    except Exception:
        return False, None

async def send_until_target(tokens, uid, server_name, target_success=1000):
    url = get_url(server_name)
    connector = aiohttp.TCPConnector(limit=80, limit_per_host=80, ttl_dns_cache=300, enable_cleanup_closed=True)
    total_success = 0
    total_sent = 0
    player_info = None
    BATCH_SIZE = 80
    start_time = time.time()

    async with aiohttp.ClientSession(connector=connector) as session:
        data = bytes.fromhex(encrypt_api("08" + Encrypt_ID(str(uid)) + "1801"))

        while total_success < target_success:
            current_batch = min(BATCH_SIZE, target_success - total_success)
            tasks = [
                asyncio.create_task(visit(session, url, tokens[(total_sent + i) % len(tokens)], uid, data))
                for i in range(current_batch)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            if player_info is None:
                for res in results:
                    if isinstance(res, tuple) and len(res) == 2:
                        success, raw_bytes = res
                        if success and raw_bytes:
                            info = parse_protobuf_response(raw_bytes)
                            if info and info.get("nickname"):
                                player_info = info
                                break

            batch_success = 0
            for res in results:
                if isinstance(res, tuple) and res[0]:
                    batch_success += 1

            total_success += batch_success
            total_sent += current_batch

            if batch_success == 0 and total_sent > (BATCH_SIZE * 3):
                break

            await asyncio.sleep(0.04)

    elapsed = round(time.time() - start_time, 2)
    return total_success, total_sent, player_info, elapsed

# ═══════════════ WEB APP FRONTEND (HTML5 + NEON CYBER UI) ═══════════════

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CODEX | Free Fire Visit Booster Web App</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090a10;
      --card-bg: rgba(18, 22, 36, 0.75);
      --card-border: rgba(0, 243, 255, 0.25);
      --neon-cyan: #00f3ff;
      --neon-purple: #b026ff;
      --neon-pink: #ff007f;
      --neon-green: #00ff88;
      --text-main: #f0f4fc;
      --text-muted: #8b9bb4;
      --font-display: 'Orbitron', sans-serif;
      --font-body: 'Rajdhani', sans-serif;
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      user-select: none;
    }
    body {
      background: radial-gradient(circle at 50% 10%, #15182e 0%, var(--bg) 100%);
      color: var(--text-main);
      font-family: var(--font-body);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 16px;
      overflow-x: hidden;
    }
    .grid-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: linear-gradient(to right, rgba(0,243,255,0.03) 1px, transparent 1px),
                  linear-gradient(to bottom, rgba(0,243,255,0.03) 1px, transparent 1px);
      background-size: 32px 32px;
      pointer-events: none;
      z-index: 0;
    }
    .container {
      position: relative;
      z-index: 1;
      width: 100%;
      max-width: 460px;
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 28px 24px;
      box-shadow: 0 0 40px rgba(0, 243, 255, 0.15), 0 20px 40px rgba(0, 0, 0, 0.6);
      animation: fadeIn 0.6s ease-out;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(15px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .header {
      text-align: center;
      margin-bottom: 24px;
    }
    .badge {
      display: inline-block;
      font-family: var(--font-display);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 2px;
      color: var(--neon-cyan);
      background: rgba(0, 243, 255, 0.1);
      border: 1px solid rgba(0, 243, 255, 0.3);
      padding: 4px 12px;
      border-radius: 30px;
      margin-bottom: 8px;
      text-transform: uppercase;
      box-shadow: 0 0 10px rgba(0, 243, 255, 0.2);
    }
    .title {
      font-family: var(--font-display);
      font-size: 24px;
      font-weight: 900;
      letter-spacing: 1px;
      background: linear-gradient(135deg, #fff 20%, var(--neon-cyan) 60%, var(--neon-purple) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 4px;
    }
    .subtitle {
      font-size: 14px;
      color: var(--text-muted);
      letter-spacing: 0.5px;
    }
    .form-group {
      margin-bottom: 18px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: 8px;
    }
    .server-selector {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .server-btn {
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 12px;
      font-family: var(--font-display);
      font-size: 14px;
      font-weight: 700;
      color: var(--text-muted);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.25s ease;
    }
    .server-btn:hover {
      border-color: rgba(0, 243, 255, 0.4);
      color: #fff;
    }
    .server-btn.active {
      background: linear-gradient(135deg, rgba(0, 243, 255, 0.2) 0%, rgba(176, 38, 255, 0.2) 100%);
      border-color: var(--neon-cyan);
      color: #fff;
      box-shadow: 0 0 15px rgba(0, 243, 255, 0.3);
    }
    .input-box {
      width: 100%;
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(0, 243, 255, 0.25);
      border-radius: 12px;
      padding: 14px 16px;
      font-family: var(--font-display);
      font-size: 16px;
      font-weight: 700;
      color: #fff;
      outline: none;
      transition: all 0.25s ease;
      letter-spacing: 1px;
    }
    .input-box:focus {
      border-color: var(--neon-cyan);
      box-shadow: 0 0 15px rgba(0, 243, 255, 0.35);
      background: rgba(0, 0, 0, 0.6);
    }
    .input-box::placeholder {
      font-family: var(--font-body);
      font-weight: 500;
      color: #4a5568;
      letter-spacing: 0.5px;
    }
    .count-selector {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }
    .count-btn {
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 10px;
      padding: 10px;
      font-family: var(--font-display);
      font-size: 13px;
      font-weight: 700;
      color: var(--text-muted);
      cursor: pointer;
      text-align: center;
      transition: all 0.25s ease;
    }
    .count-btn.active {
      background: rgba(176, 38, 255, 0.25);
      border-color: var(--neon-purple);
      color: #fff;
      box-shadow: 0 0 12px rgba(176, 38, 255, 0.3);
    }
    .boost-btn {
      width: 100%;
      margin-top: 10px;
      background: linear-gradient(135deg, var(--neon-cyan) 0%, var(--neon-purple) 100%);
      border: none;
      border-radius: 14px;
      padding: 16px;
      font-family: var(--font-display);
      font-size: 15px;
      font-weight: 900;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: #05070f;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      box-shadow: 0 0 25px rgba(0, 243, 255, 0.4);
      transition: all 0.3s ease;
    }
    .boost-btn:hover:not(:disabled) {
      transform: translateY(-2px);
      box-shadow: 0 0 35px rgba(0, 243, 255, 0.6);
      filter: brightness(1.1);
    }
    .boost-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none;
    }
    .status-card {
      display: none;
      margin-top: 20px;
      background: rgba(0, 0, 0, 0.45);
      border: 1px solid rgba(0, 243, 255, 0.3);
      border-radius: 14px;
      padding: 16px;
      animation: fadeIn 0.4s ease;
    }
    .progress-bar-bg {
      width: 100%;
      height: 8px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 4px;
      overflow: hidden;
      margin: 12px 0 8px 0;
    }
    .progress-bar-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--neon-cyan), var(--neon-green));
      border-radius: 4px;
      transition: width 0.3s ease;
      box-shadow: 0 0 10px var(--neon-cyan);
    }
    .player-card {
      display: none;
      margin-top: 16px;
      background: rgba(0, 255, 136, 0.05);
      border: 1px solid rgba(0, 255, 136, 0.3);
      border-radius: 12px;
      padding: 14px;
      font-size: 14px;
    }
    .player-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
    }
    .player-row:last-child {
      margin-bottom: 0;
    }
    .player-label {
      color: var(--text-muted);
    }
    .player-val {
      font-weight: 700;
      color: #fff;
    }
    .footer {
      margin-top: 20px;
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
      letter-spacing: 0.5px;
    }
    .status-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      background: var(--neon-green);
      border-radius: 50%;
      margin-right: 6px;
      box-shadow: 0 0 8px var(--neon-green);
    }
    .spinner {
      border: 3px solid rgba(0, 0, 0, 0.3);
      border-top: 3px solid #05070f;
      border-radius: 50%;
      width: 18px;
      height: 18px;
      animation: spin 0.8s linear infinite;
      display: none;
    }
    @keyframes spin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }
  </style>
</head>
<body>
  <div class="grid-overlay"></div>

  <div class="container">
    <div class="header">
      <div class="badge"><span class="status-dot"></span>Online Engine v2.0</div>
      <h1 class="title">CODEX VISITS</h1>
      <p class="subtitle">Free Fire Profile Visit Booster Web App</p>
    </div>

    <!-- Server Selector -->
    <div class="form-group">
      <label>1. Select Server</label>
      <div class="server-selector">
        <button class="server-btn active" data-server="IND" onclick="selectServer('IND')">🇮🇳 INDIA</button>
        <button class="server-btn" data-server="BD" onclick="selectServer('BD')">🇧🇩 BANGLADESH</button>
      </div>
    </div>

    <!-- UID Input -->
    <div class="form-group">
      <label>2. Enter Target Player UID</label>
      <input type="number" id="uidInput" class="input-box" placeholder="e.g. 19137608188" autocomplete="off" />
    </div>

    <!-- Visit Count -->
    <div class="form-group">
      <label>3. Select Visits Target</label>
      <div class="count-selector">
        <button class="count-btn" data-count="100" onclick="selectCount(100)">100</button>
        <button class="count-btn" data-count="500" onclick="selectCount(500)">500</button>
        <button class="count-btn active" data-count="1000" onclick="selectCount(1000)">1,000</button>
      </div>
    </div>

    <!-- Action Button -->
    <button id="boostBtn" class="boost-btn" onclick="startBoost()">
      <div class="spinner" id="btnSpinner"></div>
      <span id="btnText">🚀 START BOOST</span>
    </button>

    <!-- Realtime Status & Progress -->
    <div id="statusCard" class="status-card">
      <div style="display: flex; justify-content: space-between; font-size: 14px;">
        <span id="statusMessage" style="color: var(--neon-cyan); font-weight: 700;">Delivering packets...</span>
        <span id="progressPercent" style="font-family: var(--font-display); font-weight: 700;">0%</span>
      </div>
      <div class="progress-bar-bg">
        <div id="progressBar" class="progress-bar-fill"></div>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted); margin-top: 4px;">
        <span id="deliveredCount">Sent: 0</span>
        <span id="elapsedTime">Time: 0.0s</span>
      </div>
    </div>

    <!-- Player Info Card -->
    <div id="playerCard" class="player-card">
      <div class="player-row">
        <span class="player-label">Player Name:</span>
        <span id="pName" class="player-val" style="color: var(--neon-green);">-</span>
      </div>
      <div class="player-row">
        <span class="player-label">Level:</span>
        <span id="pLevel" class="player-val">-</span>
      </div>
      <div class="player-row">
        <span class="player-label">Likes:</span>
        <span id="pLikes" class="player-val">-</span>
      </div>
      <div class="player-row">
        <span class="player-label">Region:</span>
        <span id="pRegion" class="player-val">-</span>
      </div>
    </div>

    <div class="footer">
      CODEX BOOST ENGINE • 100% Anti-Ban Safe • WebApp Ready
    </div>
  </div>

  <script>
    let selectedServer = 'IND';
    let selectedCount = 1000;
    let boostRunning = false;

    // Telegram WebApp Auto-Expansion
    if (window.Telegram && window.Telegram.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
    }

    function selectServer(srv) {
      if (boostRunning) return;
      selectedServer = srv;
      document.querySelectorAll('.server-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-server') === srv);
      });
    }

    function selectCount(cnt) {
      if (boostRunning) return;
      selectedCount = cnt;
      document.querySelectorAll('.count-btn').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.getAttribute('data-count')) === cnt);
      });
    }

    async function startBoost() {
      const uid = document.getElementById('uidInput').value.trim();
      if (!uid || isNaN(uid) || uid.length < 5) {
        alert("Please enter a valid numeric Free Fire UID!");
        return;
      }

      boostRunning = true;
      const boostBtn = document.getElementById('boostBtn');
      const btnSpinner = document.getElementById('btnSpinner');
      const btnText = document.getElementById('btnText');
      const statusCard = document.getElementById('statusCard');
      const playerCard = document.getElementById('playerCard');
      const progressBar = document.getElementById('progressBar');
      const progressPercent = document.getElementById('progressPercent');
      const statusMessage = document.getElementById('statusMessage');
      const deliveredCount = document.getElementById('deliveredCount');
      const elapsedTime = document.getElementById('elapsedTime');

      boostBtn.disabled = true;
      btnSpinner.style.display = 'inline-block';
      btnText.innerText = "PROCESSING...";
      statusCard.style.display = 'block';
      playerCard.style.display = 'none';
      progressBar.style.width = '10%';
      progressPercent.innerText = '10%';
      statusMessage.innerText = 'Connecting to Garena clusters...';

      let timer = 0;
      const interval = setInterval(() => {
        timer += 0.2;
        elapsedTime.innerText = `Time: ${timer.toFixed(1)}s`;
        if (parseFloat(progressBar.style.width) < 85) {
          const nw = Math.min(85, parseFloat(progressBar.style.width) + 12);
          progressBar.style.width = nw + '%';
          progressPercent.innerText = Math.floor(nw) + '%';
        }
      }, 200);

      try {
        const response = await fetch('/api/boost', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            uid: parseInt(uid),
            server: selectedServer,
            count: selectedCount
          })
        });

        clearInterval(interval);
        const data = await response.json();

        if (response.status === 429) {
          statusMessage.innerText = data.error || '⏳ Cooldown active! Please wait 10s.';
          statusMessage.style.color = 'var(--neon-pink)';
          startCooldownTimer(data.remaining || 10);
          return;
        }

        if (response.ok && data.success > 0) {
          progressBar.style.width = '100%';
          progressPercent.innerText = '100%';
          statusMessage.innerText = `🎉 Boost Complete! (${data.success} visits delivered)`;
          statusMessage.style.color = 'var(--neon-green)';
          deliveredCount.innerText = `Delivered: ${data.success}/${selectedCount}`;
          elapsedTime.innerText = `Finished in: ${data.elapsed}s`;

          if (data.player_info) {
            document.getElementById('pName').innerText = data.player_info.nickname || "Verified Player";
            document.getElementById('pLevel').innerText = data.player_info.level || "N/A";
            document.getElementById('pLikes').innerText = data.player_info.likes || "N/A";
            document.getElementById('pRegion').innerText = data.player_info.region || selectedServer;
            playerCard.style.display = 'block';
          }
          startCooldownTimer(10);
        } else {
          statusMessage.innerText = `❌ Error: ${data.error || 'Failed to deliver visits'}`;
          statusMessage.style.color = 'var(--neon-pink)';
        }
      } catch (err) {
        clearInterval(interval);
        statusMessage.innerText = `❌ Connection Error: ${err.message}`;
        statusMessage.style.color = 'var(--neon-pink)';
      } finally {
        boostRunning = false;
        btnSpinner.style.display = 'none';
      }
    }

    function startCooldownTimer(seconds = 10) {
      boostBtn.disabled = true;
      btnSpinner.style.display = 'none';
      let remaining = seconds;
      btnText.innerText = `⏳ COOLDOWN: ${remaining}s`;
      const cdInterval = setInterval(() => {
        remaining -= 1;
        if (remaining > 0) {
          btnText.innerText = `⏳ COOLDOWN: ${remaining}s`;
        } else {
          clearInterval(cdInterval);
          boostBtn.disabled = false;
          btnText.innerText = "🚀 BOOST PROFILE NOW";
        }
      }, 1000);
    }
  </script>
</body>
</html>
"""

# ═══════════════ RATE LIMITING & COOLDOWN (STRICTLY 10s) ═══════════════
IP_COOLDOWNS = {}
UID_COOLDOWNS = {}
COOLDOWN_SECONDS = 10

def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"

def check_cooldown(ip, uid):
    now = time.time()
    for k in [k for k, v in IP_COOLDOWNS.items() if now - v > 60]:
        IP_COOLDOWNS.pop(k, None)
    for k in [k for k, v in UID_COOLDOWNS.items() if now - v > 60]:
        UID_COOLDOWNS.pop(k, None)

    # Check IP cooldown (Strictly 10s)
    last_ip = IP_COOLDOWNS.get(ip, 0)
    if now - last_ip < COOLDOWN_SECONDS:
        rem = max(1, int(COOLDOWN_SECONDS - (now - last_ip)))
        return False, f"⏳ IP Cooldown Active! Please wait {rem}s before submitting again.", rem

    # Check UID cooldown (Strictly 10s)
    last_uid = UID_COOLDOWNS.get(str(uid), 0)
    if now - last_uid < COOLDOWN_SECONDS:
        rem = max(1, int(COOLDOWN_SECONDS - (now - last_uid)))
        return False, f"⏳ UID Cooldown Active! UID {uid} was boosted recently. Please wait {rem}s.", rem

    IP_COOLDOWNS[ip] = now
    UID_COOLDOWNS[str(uid)] = now
    return True, "", 0

# ═══════════════ API ROUTES ═══════════════

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/status", methods=["GET"])
def api_status():
    ind_tokens = load_tokens("IND")
    bd_tokens = load_tokens("BD")
    return jsonify({
        "status": "online",
        "stock": {
            "IND": len(ind_tokens),
            "BD": len(bd_tokens)
        },
        "servers": ["IND", "BD"],
        "cooldown_seconds": COOLDOWN_SECONDS
    }), 200

@app.route("/api/boost", methods=["POST"])
def api_boost():
    try:
        data = request.get_json(force=True) or {}
        uid = int(data.get("uid", 0))
        server = str(data.get("server", "IND")).upper()
        count = int(data.get("count", 1000))
    except Exception as e:
        return jsonify({"error": f"Invalid payload: {e}"}), 400

    if not uid or uid <= 0:
        return jsonify({"error": "Invalid player UID"}), 400

    # Enforce strictly 10-second Cooldown per IP and per UID
    client_ip = get_client_ip()
    allowed, err_msg, rem_secs = check_cooldown(client_ip, uid)
    if not allowed:
        return jsonify({
            "error": err_msg,
            "remaining": rem_secs,
            "cooldown": True
        }), 429

    tokens = load_tokens(server)
    if not tokens:
        return jsonify({"error": f"No active tokens available for region {server}"}), 503

    success, sent, info, elapsed = asyncio.run(send_until_target(tokens, uid, server, target_success=count))

    return jsonify({
        "success": success,
        "total_sent": sent,
        "elapsed": elapsed,
        "server": server,
        "uid": uid,
        "player_info": info
    }), 200

# Legacy Endpoint for Compatibility: /<server>/<uid>
@app.route("/<string:server>/<int:uid>", methods=["GET"])
def legacy_send_visits(server, uid):
    server = server.upper()
    client_ip = get_client_ip()
    allowed, err_msg, rem_secs = check_cooldown(client_ip, uid)
    if not allowed:
        return jsonify({
            "error": err_msg,
            "remaining": rem_secs,
            "cooldown": True
        }), 429

    tokens = load_tokens(server)
    if not tokens:
        return jsonify({"error": "No valid tokens found"}), 500

    success, sent, player_info, elapsed = asyncio.run(send_until_target(tokens, uid, server, target_success=100))
    if player_info:
        return jsonify({
            "success": success,
            "fail": sent - success,
            "uid": player_info.get("uid", uid),
            "nickname": player_info.get("nickname", ""),
            "likes": player_info.get("likes", 0),
            "level": player_info.get("level", 0),
            "region": player_info.get("region", server),
            "elapsed": elapsed
        }), 200

    return jsonify({
        "success": success,
        "fail": sent - success,
        "uid": uid,
        "elapsed": elapsed
    }), 200

import subprocess

BOT_PROCESS = None

def start_telegram_bot_background():
    global BOT_PROCESS
    bot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
    while True:
        try:
            print(f"🚀 [WATCHDOG] Launching CODEX Telegram Bot process ({bot_path})...")
            BOT_PROCESS = subprocess.Popen(
                [sys.executable, bot_path],
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            BOT_PROCESS.wait()
            print("⚠️ [WATCHDOG] Telegram Bot process exited. Auto-restarting in 3 seconds...")
            time.sleep(3)
        except Exception as e:
            print(f"❌ [WATCHDOG] Telegram Bot launch error: {e}. Retrying in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    import threading
    # Launch Telegram Bot with resilient Watchdog process alongside the Web App
    bot_thread = threading.Thread(target=start_telegram_bot_background, daemon=True)
    bot_thread.start()

    # Use custom port 25343 as requested by user / hosting proxy
    port = int(os.environ.get("PORT", 25343))
    print(f"Starting CODEX Web App on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
