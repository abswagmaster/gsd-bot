"""Git sync layer for GSD task files.

On Railway: GSD_DIR is a git clone of the `data` branch. Pulls before reads,
pushes after writes. Auth via GITHUB_TOKEN env var.

Locally: if SYNC_DISABLED=1, this module is a no-op (you'd use a separate
launchd/cron loop on each Mac to keep ~/.gsd in sync).
"""
from __future__ import annotations
import os
import subprocess
import time
from pathlib import Path

GSD_DIR = Path(os.getenv("GSD_DIR", str(Path.home() / ".gsd")))
REPO_URL = os.getenv("GIT_REPO_URL", "")  # e.g. https://github.com/user/repo.git
BRANCH = os.getenv("GIT_BRANCH", "data")
TOKEN = os.getenv("GITHUB_TOKEN", "")
SYNC_DISABLED = os.getenv("SYNC_DISABLED", "0") == "1"

_last_pull = 0.0
_PULL_THROTTLE_SEC = 5  # Don't pull more than once per N seconds


def _authed_url() -> str:
    if not REPO_URL or not TOKEN:
        return ""
    # Inject token as basic auth: https://x-access-token:TOKEN@github.com/...
    if REPO_URL.startswith("https://"):
        return REPO_URL.replace("https://", f"https://x-access-token:{TOKEN}@", 1)
    return REPO_URL


def _run(args: list[str], cwd: Path = GSD_DIR, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), check=check, capture_output=True, text=True)


def ensure_clone() -> None:
    """Clone the data branch into GSD_DIR if it isn't already a git repo."""
    if SYNC_DISABLED:
        return
    if not REPO_URL or not TOKEN:
        print("[sync] GIT_REPO_URL or GITHUB_TOKEN missing — skipping sync")
        return
    GSD_DIR.mkdir(parents=True, exist_ok=True)
    if (GSD_DIR / ".git").exists():
        return
    url = _authed_url()
    # If GSD_DIR has files but isn't a git repo, wipe and reclone for cleanliness
    if any(GSD_DIR.iterdir()):
        print(f"[sync] {GSD_DIR} has stale files — wiping and re-cloning")
        for child in GSD_DIR.iterdir():
            if child.is_dir():
                subprocess.run(["rm", "-rf", str(child)], check=False)
            else:
                child.unlink()
    print(f"[sync] cloning {BRANCH} branch into {GSD_DIR}")
    _run(["git", "clone", "-b", BRANCH, url, "."], cwd=GSD_DIR)
    _run(["git", "config", "user.email", "bot@gsd.local"])
    _run(["git", "config", "user.name", "GSD Bot"])


def pull() -> None:
    """Throttled git pull. Safe to call frequently."""
    global _last_pull
    if SYNC_DISABLED or not REPO_URL or not TOKEN:
        return
    now = time.time()
    if now - _last_pull < _PULL_THROTTLE_SEC:
        return
    _last_pull = now
    try:
        _run(["git", "pull", "--rebase", "origin", BRANCH], check=False)
    except Exception as e:
        print(f"[sync] pull failed: {e}")


def push(message: str) -> None:
    """Commit any changes and push. No-op if there's nothing to commit."""
    if SYNC_DISABLED or not REPO_URL or not TOKEN:
        return
    try:
        _run(["git", "add", "-A"])
        # Skip if nothing changed
        status = _run(["git", "status", "--porcelain"], check=False)
        if not status.stdout.strip():
            return
        _run(["git", "commit", "-m", message], check=False)
        # Pull-rebase first to avoid push conflicts, then push
        _run(["git", "pull", "--rebase", "origin", BRANCH], check=False)
        result = _run(["git", "push", "origin", BRANCH], check=False)
        if result.returncode != 0:
            print(f"[sync] push failed: {result.stderr}")
    except Exception as e:
        print(f"[sync] push error: {e}")
