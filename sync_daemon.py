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


import re as _re
from datetime import timedelta as _td


def _blank_sections() -> dict:
    return {k: [] for k in gsd.SECTIONS}


def _migrate_file(path) -> bool:
    """If file has the wrong format, rewrite as Ayush/Rohit with existing tasks
    placed under Ayush's No Sleep. Returns True if anything changed."""
    if not path.exists():
        return False
    text = path.read_text()
    if not text.strip():
        path.write_text(gsd._serialize(_blank_sections()))
        return True
    if "## Ayush" in text and "## Rohit" in text:
        return False
    sections = _blank_sections()
    for line in text.splitlines():
        if _re.match(r"\s*- \[.\]", line):
            sections["ayush_no_sleep"].append(line)
    path.write_text(gsd._serialize(sections))
    return True


def migrate_all_daily_files() -> None:
    """Ensure every file in Daily/ has the Ayush/Rohit structure."""
    daily_dir = gsd.GSD_DIR / gsd.NOTEBOOK
    if not daily_dir.exists():
        return
    changed = False
    for path in daily_dir.glob("*.md"):
        if _migrate_file(path):
            changed = True
            print(f"[gsd] migrated {path.name}")
    if changed:
        push("migrate daily files to Ayush/Rohit format")


def ensure_today() -> None:
    """Pull, then ensure today's file exists in the right format AND
    merge yesterday's unchecked tasks into today (4 AM carry-forward).
    Safe to run repeatedly — duplicates are skipped."""
    pull()
    today = gsd._logical_today()
    yesterday = today - _td(days=1)
    today_path = gsd.GSD_DIR / gsd.NOTEBOOK / f"{today.isoformat()}.md"
    yest_path = gsd.GSD_DIR / gsd.NOTEBOOK / f"{yesterday.isoformat()}.md"
    today_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure today's file exists in correct format
    if not today_path.exists() or not today_path.read_text().strip():
        today_path.write_text(gsd._serialize(_blank_sections()))
        print(f"[gsd] created blank {today_path.name}")
    else:
        if _migrate_file(today_path):
            print(f"[gsd] migrated {today_path.name}")

    # Merge yesterday's unchecked into today (skip if no yesterday file)
    if not yest_path.exists():
        push("ensure today")
        return
    _migrate_file(yest_path)  # ensure yesterday is in correct format too
    yest_sections = gsd._parse(yest_path.read_text())
    today_sections = gsd._parse(today_path.read_text())

    added = 0
    for k in gsd.SECTIONS:
        existing = set(l.strip() for l in today_sections[k])
        for l in yest_sections[k]:
            if _re.match(r"\s*- \[ \]", l) and l.strip() not in existing:
                today_sections[k].append(l)
                existing.add(l.strip())
                added += 1
    if added:
        today_path.write_text(gsd._serialize(today_sections))
        print(f"[gsd] carried forward {added} unchecked tasks from {yest_path.name}")
    push("ensure today")


def run() -> None:
    if not ensure_setup():
        return

    # Migrate any existing files to the correct format, then ensure today
    migrate_all_daily_files()
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
