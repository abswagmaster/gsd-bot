"""
GSD Sync Daemon
Watches ~/.gsd/ for changes and syncs via git, so AB and Rogan
stay in sync when using the native GSD macOS app.

Run once and leave it in the background:
    python3 sync_daemon.py &

Or add it to your Login Items / launchd to auto-start on boot.
"""
from __future__ import annotations
import os
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Import gsd so we can create today's file with carry-forward
import sys
sys.path.insert(0, str(Path(__file__).parent))
import gsd

GSD_DIR = Path(os.getenv("GSD_DIR", str(Path.home() / ".gsd")))
REPO_URL = os.getenv("GIT_REPO_URL", "")
BRANCH = os.getenv("GIT_BRANCH", "data")
TOKEN = os.getenv("GITHUB_TOKEN", "")

PUSH_DEBOUNCE_SEC = 3   # wait this long after a change before pushing
PULL_INTERVAL_SEC = 30  # pull from remote every N seconds


def _authed_url() -> str:
    if REPO_URL.startswith("https://") and TOKEN:
        return REPO_URL.replace("https://", f"https://x-access-token:{TOKEN}@", 1)
    return REPO_URL


def _run(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(GSD_DIR), capture_output=True, text=True, check=check)


def has_changes() -> bool:
    return bool(_run(["git", "status", "--porcelain"]).stdout.strip())


def push(message: str = "gsd: sync") -> None:
    _run(["git", "add", "-A"])
    if not has_changes():
        return
    _run(["git", "commit", "-m", message])
    _run(["git", "pull", "--rebase", "origin", BRANCH])
    result = _run(["git", "push", "origin", BRANCH])
    if result.returncode == 0:
        print(f"[sync] pushed: {message}")
    else:
        print(f"[sync] push failed: {result.stderr.strip()}")


def pull() -> None:
    result = _run(["git", "pull", "--rebase", "origin", BRANCH])
    if result.returncode == 0 and result.stdout.strip() and "Already up to date" not in result.stdout:
        print(f"[sync] pulled changes")


def snapshot() -> dict[Path, float]:
    """Return mtime for every .md file under GSD_DIR."""
    return {p: p.stat().st_mtime for p in GSD_DIR.rglob("*.md") if ".git" not in p.parts}


def ensure_setup() -> bool:
    if not REPO_URL or not TOKEN:
        print("[sync] GIT_REPO_URL or GITHUB_TOKEN not set in .env — exiting")
        return False
    if not (GSD_DIR / ".git").exists():
        print(f"[sync] {GSD_DIR} is not a git repo.")
        print("       Run the full setup first (see README), or set GSD_DIR to the cloned data branch.")
        return False
    # Configure identity if needed
    _run(["git", "config", "user.email", "gsd@local"])
    _run(["git", "config", "user.name", "GSD Sync"])
    # Make sure remote uses authed URL
    _run(["git", "remote", "set-url", "origin", _authed_url()])
    return True


def ensure_today() -> None:
    """Create today's file with carried-forward tasks if it doesn't exist yet.
    Pulls first so we don't duplicate work if the other machine already created it."""
    pull()
    path = gsd.get_today_path()
    if not path.exists() or not path.read_text().strip():
        sections = gsd._carry_forward()
        path.write_text(gsd._serialize(sections))
        push("create today with carry-forward")
        print(f"[gsd] created {path.name} with carry-forward")


def run() -> None:
    if not ensure_setup():
        return

    # Always ensure today's file exists on startup
    ensure_today()

    print(f"[sync] watching {GSD_DIR} — pull every {PULL_INTERVAL_SEC}s, push on change")
    last_pull = 0.0
    last_change_time: float | None = None
    last_date = gsd._logical_today()
    prev_snap = snapshot()

    while True:
        time.sleep(1)
        now = time.time()

        # Check if the logical day has rolled over (4 AM boundary)
        today = gsd._logical_today()
        if today != last_date:
            last_date = today
            pull()
            ensure_today()
            prev_snap = snapshot()

        # Detect local file changes
        curr_snap = snapshot()
        if curr_snap != prev_snap:
            prev_snap = curr_snap
            last_change_time = now  # reset debounce

        # Push after debounce
        if last_change_time and (now - last_change_time) >= PUSH_DEBOUNCE_SEC:
            last_change_time = None
            push()
            prev_snap = snapshot()

        # Periodic pull
        if now - last_pull >= PULL_INTERVAL_SEC:
            last_pull = now
            pull()
            prev_snap = snapshot()  # update after pull so we don't re-push remote changes


if __name__ == "__main__":
    run()
