#!/bin/bash
# One-shot setup for Rohit's Mac.
# Installs the custom GSD app, initializes ~/.gsd/ as a git repo on the data branch,
# and starts the sync daemon.

set -e

REPO_DIR="$HOME/gsd-bot"
REPO_URL="https://github.com/abswagmaster/gsd-bot.git"

# GitHub token — set this in your environment before running:
#   export GITHUB_TOKEN=ghp_xxx
#   ./setup_rohit.sh
if [ -z "$GITHUB_TOKEN" ]; then
    echo "ERROR: GITHUB_TOKEN env var is not set. Ask Ayush for the token, then run:"
    echo "  export GITHUB_TOKEN=ghp_xxx"
    echo "  ./setup_rohit.sh"
    exit 1
fi
AUTHED_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/abswagmaster/gsd-bot.git"

echo "=== 1. Cloning gsd-bot repo to $REPO_DIR ==="
if [ ! -d "$REPO_DIR" ]; then
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

echo "=== 2. Installing custom GSD app ==="
if [ -d "/Applications/GSD.app" ]; then
    echo "Removing existing GSD.app (will need sudo)…"
    sudo rm -rf /Applications/GSD.app
fi
unzip -q dist/GSD.app.zip -d /Applications/
sudo codesign --force --deep --sign - /Applications/GSD.app
echo "GSD.app installed."

echo "=== 3. Initializing ~/.gsd/ as git repo on data branch ==="
if [ ! -d "$HOME/.gsd/.git" ]; then
    mkdir -p "$HOME/.gsd"
    cd "$HOME/.gsd"
    git init
    git config user.email "rohit@local"
    git config user.name "Rohit GSD"
    git remote add origin "$AUTHED_URL"
    git fetch origin data
    git checkout -B data origin/data
    cd "$REPO_DIR"
else
    cd "$HOME/.gsd"
    git remote set-url origin "$AUTHED_URL"
    git pull --rebase origin data
    cd "$REPO_DIR"
fi
echo "~/.gsd is now synced."

echo "=== 4. Writing .env ==="
cat > .env <<EOF
GITHUB_TOKEN=${GITHUB_TOKEN}
GIT_REPO_URL=${REPO_URL}
GIT_BRANCH=data
TZ=America/New_York
EOF

echo "=== 5. Installing Python deps ==="
pip3 install --user python-dotenv

echo "=== 6. Starting sync daemon ==="
# Kill any existing daemon
pkill -f sync_daemon.py 2>/dev/null || true
nohup python3 sync_daemon.py > /tmp/gsd_sync.log 2>&1 &
echo "Daemon started (PID: $!). Log: /tmp/gsd_sync.log"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Open GSD.app from /Applications. You'll see the Daily notebook"
echo "with both Ayush and Rohit sections. Just click under your section"
echo "and press Return to add a checkbox."
