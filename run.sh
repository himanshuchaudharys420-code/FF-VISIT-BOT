#!/bin/bash
# ══════════════════════════════════════════════════
# CODEX Free Fire Visit Booster - 1-Click VPS Runner
# ══════════════════════════════════════════════════

echo "🚀 [1/3] Updating system packages..."
apt-get update -y 2>/dev/null || sudo apt-get update -y

echo "📦 [2/3] Installing Python3, Pip, and dependencies..."
apt-get install -y python3 python3-pip python3-venv 2>/dev/null || sudo apt-get install -y python3 python3-pip python3-venv

# Create Virtual Environment to prevent Ubuntu 'externally-managed-environment' error
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

echo "⚡ [3/3] Installing Python requirements..."
pip install --upgrade pip
pip install -r requirements.txt

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Everything installed successfully!"
echo "✨ Starting CODEX Bot 24/7 in Background..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python3 app.py
