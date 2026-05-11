"""
GSD Menu Bar App
Runs in the macOS menu bar. Shows AB's and Rogan's tasks in a single dropdown.
Syncs via git (same sync.py layer as before).
"""
from __future__ import annotations
import re
import threading
import time

import rumps

import gsd
import sync

PEOPLE = ["AB", "rohitraju"]
DISPLAY_NAMES = {"AB": "AB", "rohitraju": "Rogan"}

# Seconds to show a freshly-completed task before rebuilding the menu
DONE_LINGER_SEC = 2
# Seconds between auto-refresh pulls
AUTO_REFRESH_SEC = 30


class GSDApp(rumps.App):
    def __init__(self):
        super().__init__("📋", quit_button=None)
        self._done_linger: dict[tuple[str, int], float] = {}  # (person, task_n) -> done_at
        self._build_menu()
        # Background auto-refresh thread
        t = threading.Thread(target=self._auto_refresh, daemon=True)
        t.start()

    # ── menu building ──────────────────────────────────────────────────────────

    def _build_menu(self):
        today = gsd._logical_today().isoformat()
        items = [rumps.MenuItem(f"📅  {today}", callback=None), rumps.separator]

        for person in PEOPLE:
            label = DISPLAY_NAMES[person]
            try:
                sections = gsd.read_tasks(person)
            except Exception as e:
                items.append(rumps.MenuItem(f"⚠️  {label}: {e}", callback=None))
                items.append(rumps.separator)
                continue

            all_tasks = gsd.all_tasks(sections)
            task_num = 1

            # Track how many real (non-linger) tasks each person has
            pending = [t for t in all_tasks if not _is_done(t[2])]

            items.append(rumps.MenuItem(f"── {label} ──────────────────", callback=None))

            for section_key in ("no_sleep", "best_effort"):
                emoji = "🔥" if section_key == "no_sleep" else "⚡"
                sec_label = "No Sleep" if section_key == "no_sleep" else "Best Effort"
                items.append(rumps.MenuItem(f"  {emoji} {sec_label}", callback=None))

                for line in sections[section_key]:
                    if not re.match(r"\s*- \[.\]", line):
                        task_num += 1  # keep numbering aligned even for non-checkbox lines
                        continue

                    done = _is_done(line)
                    n = task_num
                    task_num += 1
                    text = re.sub(r"\s*- \[.\]\s*", "", line).strip()

                    # Check linger — show with strikethrough-ish prefix if recently done
                    linger_key = (person, n)
                    if done:
                        linger_until = self._done_linger.get(linger_key, 0)
                        if time.time() < linger_until:
                            # Show briefly with ✓ prefix
                            item = rumps.MenuItem(f"    ✓  {text}", callback=None)
                            items.append(item)
                        # else: hide completed task entirely
                        continue

                    # Pending task — click to mark done
                    def make_toggle(p=person, num=n, lk=linger_key):
                        def toggle(_):
                            gsd.toggle_task(p, num, done=True)
                            self._done_linger[lk] = time.time() + DONE_LINGER_SEC
                            self._build_menu()
                            # After linger period, rebuild again to hide it
                            def _hide():
                                time.sleep(DONE_LINGER_SEC + 0.1)
                                self._build_menu()
                            threading.Thread(target=_hide, daemon=True).start()
                        return toggle

                    item = rumps.MenuItem(f"    ☐  {text}", callback=make_toggle())
                    items.append(item)

            items.append(rumps.separator)

        # Bottom actions
        items.append(rumps.MenuItem("＋  Add task…", callback=self.add_task))
        items.append(rumps.MenuItem("↺  Refresh", callback=self.refresh))
        items.append(rumps.separator)
        items.append(rumps.MenuItem("Quit", callback=rumps.quit_application))

        self.menu.clear()
        self.menu = items

    # ── actions ────────────────────────────────────────────────────────────────

    @rumps.clicked("＋  Add task…")
    def add_task(self, _):
        # Ask who
        person_win = rumps.Window(
            message="Whose list?",
            title="Add Task",
            default_text="",
            ok="AB",
            cancel="Rogan",
            dimensions=(0, 0),
        )
        resp = person_win.run()
        person = "AB" if resp.clicked == 1 else "rohitraju"

        # Ask task text
        task_win = rumps.Window(
            message=f"Task for {DISPLAY_NAMES[person]}:",
            title="Add Task",
            default_text="",
            ok="No Sleep 🔥",
            cancel="Best Effort ⚡",
            dimensions=(300, 24),
        )
        resp2 = task_win.run()
        if resp2.text.strip():
            section = "no_sleep" if resp2.clicked == 1 else "best_effort"
            gsd.add_task(person, resp2.text.strip(), section)
            self._build_menu()

    @rumps.clicked("↺  Refresh")
    def refresh(self, _):
        sync.pull()
        self._build_menu()

    # ── auto-refresh ───────────────────────────────────────────────────────────

    def _auto_refresh(self):
        while True:
            time.sleep(AUTO_REFRESH_SEC)
            sync.pull()
            self._build_menu()


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_done(line: str) -> bool:
    return bool(re.match(r"\s*- \[x\]", line, re.IGNORECASE))


if __name__ == "__main__":
    sync.ensure_clone()
    GSDApp().run()
