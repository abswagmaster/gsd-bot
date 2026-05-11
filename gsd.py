from __future__ import annotations
import os
from pathlib import Path
from datetime import date, datetime, timedelta
import zoneinfo
import re
import sync

GSD_DIR = Path(os.getenv("GSD_DIR", str(Path.home() / ".gsd")))
NOTEBOOK = "Daily"  # shared notebook folder inside ~/.gsd/

_LOCAL_TZ = zoneinfo.ZoneInfo(os.getenv("TZ", "America/New_York"))
_DAY_START_HOUR = 4  # new day begins at 4 AM


def _logical_today() -> date:
    now = datetime.now(tz=_LOCAL_TZ)
    if now.hour < _DAY_START_HOUR:
        return (now - timedelta(days=1)).date()
    return now.date()


def get_today_path() -> Path:
    today = _logical_today().isoformat()
    path = GSD_DIR / NOTEBOOK / f"{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _find_recent_path() -> Path | None:
    for days_back in range(1, 31):
        d = (_logical_today() - timedelta(days=days_back)).isoformat()
        p = GSD_DIR / NOTEBOOK / f"{d}.md"
        if p.exists() and p.read_text().strip():
            return p
    return None


# Section keys
SECTIONS = ["ayush_no_sleep", "ayush_best_effort", "rohit_no_sleep", "rohit_best_effort"]

_HEADERS = {
    "ayush": "## Ayush",
    "rohit": "## Rohit",
    "no_sleep": "### No Sleep",
    "best_effort": "### Best Effort",
}


def _parse(text: str) -> dict:
    sections: dict[str, list[str]] = {k: [] for k in SECTIONS}
    person = None
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## Ayush":
            person, section = "ayush", None
        elif stripped == "## Rohit":
            person, section = "rohit", None
        elif stripped == "### No Sleep":
            section = "no_sleep"
        elif stripped == "### Best Effort":
            section = "best_effort"
        elif stripped.startswith("## ") or stripped.startswith("### "):
            section = None
        elif person and section:
            sections[f"{person}_{section}"].append(line)
    for k in sections:
        while sections[k] and not sections[k][-1].strip():
            sections[k].pop()
    return sections


def _serialize(sections: dict) -> str:
    parts = []
    for person in ("ayush", "rohit"):
        parts.append(f"## {person.capitalize()}")
        parts.append("")
        for sec, label in (("no_sleep", "No Sleep"), ("best_effort", "Best Effort")):
            parts.append(f"### {label}")
            parts.extend(sections.get(f"{person}_{sec}", []))
            parts.append("")
    return "\n".join(parts)


def _carry_forward() -> dict:
    recent = _find_recent_path()
    if not recent:
        return {k: [] for k in SECTIONS}
    prev = _parse(recent.read_text())
    return {
        k: [l for l in prev[k] if re.match(r"\s*- \[ \]", l)]
        for k in SECTIONS
    }


def read_tasks() -> dict:
    sync.pull()
    path = get_today_path()
    if not path.exists() or not path.read_text().strip():
        sections = _carry_forward()
        path.write_text(_serialize(sections))
        sync.push("create today")
        return sections
    return _parse(path.read_text())


def all_tasks(sections: dict) -> list[tuple[str, int, str]]:
    """(section_key, line_index, line) for every checkbox line."""
    tasks = []
    for key in SECTIONS:
        for i, line in enumerate(sections[key]):
            if re.match(r"\s*- \[.\]", line):
                tasks.append((key, i, line))
    return tasks


def add_task(person: str, text: str, section: str) -> None:
    """person: 'ayush' or 'rohit'. section: 'no_sleep' or 'best_effort'."""
    sections = read_tasks()
    key = f"{person}_{section}"
    sections[key].append(f"- [ ] {text}")
    get_today_path().write_text(_serialize(sections))
    sync.push(f"{person}: add task")


def toggle_task(n: int, done: bool) -> tuple[str, str] | None:
    sections = read_tasks()
    tasks = all_tasks(sections)
    if n < 1 or n > len(tasks):
        return None
    key, idx, line = tasks[n - 1]
    if done:
        new_line = re.sub(r"- \[ \]", "- [x]", line, count=1)
    else:
        new_line = re.sub(r"- \[x\]", "- [ ]", line, count=1, flags=re.IGNORECASE)
    sections[key][idx] = new_line
    get_today_path().write_text(_serialize(sections))
    sync.push(f"toggle task #{n}")
    task_text = re.sub(r"\s*- \[.\]\s*", "", new_line).strip()
    return key, task_text
