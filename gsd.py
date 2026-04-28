from __future__ import annotations
import os
from pathlib import Path
from datetime import date, datetime, timedelta
import zoneinfo
import re
import sync

# Allow override via env var (e.g. Railway volume mount). Defaults to ~/.gsd locally.
GSD_DIR = Path(os.getenv("GSD_DIR", str(Path.home() / ".gsd")))

_LOCAL_TZ = zoneinfo.ZoneInfo(os.getenv("TZ", "America/New_York"))
_DAY_START_HOUR = 4  # new day begins at 4 AM local time


def _logical_today() -> date:
    now = datetime.now(tz=_LOCAL_TZ)
    if now.hour < _DAY_START_HOUR:
        return (now - timedelta(days=1)).date()
    return now.date()


def get_today_path(person: str) -> Path:
    today = _logical_today().isoformat()
    path = GSD_DIR / person / f"{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_SYSTEM_NOTEBOOKS = {"Daily", "daily", "Work", "Personal"}

def list_people() -> list[str]:
    """Return all person notebooks, excluding built-in GSD notebook names."""
    if not GSD_DIR.exists():
        return []
    return sorted(
        p.name for p in GSD_DIR.iterdir()
        if p.is_dir() and p.name not in _SYSTEM_NOTEBOOKS and any(p.glob("*.md"))
    )


def _find_recent_path(person: str) -> Path | None:
    for days_back in range(1, 31):
        d = (_logical_today() - timedelta(days=days_back)).isoformat()
        p = GSD_DIR / person / f"{d}.md"
        if p.exists() and p.read_text().strip():
            return p
    return None


def _parse(text: str) -> dict:
    sections: dict[str, list[str]] = {"no_sleep": [], "best_effort": []}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## No Sleep":
            current = "no_sleep"
            continue
        if stripped == "## Best Effort":
            current = "best_effort"
            continue
        if stripped.startswith("## "):
            current = None
            continue
        if current is not None:
            sections[current].append(line)
    for k in sections:
        while sections[k] and not sections[k][-1].strip():
            sections[k].pop()
    return sections


def _serialize(sections: dict) -> str:
    parts = []
    parts.append("## No Sleep")
    parts.extend(sections.get("no_sleep", []))
    parts.append("")
    parts.append("## Best Effort")
    parts.extend(sections.get("best_effort", []))
    parts.append("")
    return "\n".join(parts)


def _carry_forward(person: str) -> dict:
    recent = _find_recent_path(person)
    if not recent:
        return {"no_sleep": [], "best_effort": []}
    prev = _parse(recent.read_text())
    return {
        "no_sleep": [l for l in prev["no_sleep"] if re.match(r"\s*- \[ \]", l)],
        "best_effort": [l for l in prev["best_effort"] if re.match(r"\s*- \[ \]", l)],
    }


def read_tasks(person: str) -> dict:
    sync.pull()
    path = get_today_path(person)
    if not path.exists() or not path.read_text().strip():
        sections = _carry_forward(person)
        path.write_text(_serialize(sections))
        sync.push(f"{person}: create today")
        return sections
    return _parse(path.read_text())


def all_tasks(sections: dict) -> list[tuple[str, int, str]]:
    """(section_key, line_index, line) for every checkbox line, No Sleep first."""
    tasks = []
    for key in ("no_sleep", "best_effort"):
        for i, line in enumerate(sections[key]):
            if re.match(r"\s*- \[.\]", line):
                tasks.append((key, i, line))
    return tasks


def add_task(person: str, text: str, section: str) -> None:
    sections = read_tasks(person)
    sections[section].append(f"- [ ] {text}")
    get_today_path(person).write_text(_serialize(sections))
    sync.push(f"{person}: add {section}")


def toggle_task(person: str, n: int, done: bool) -> tuple[str, str] | None:
    sections = read_tasks(person)
    tasks = all_tasks(sections)
    if n < 1 or n > len(tasks):
        return None
    key, idx, line = tasks[n - 1]
    if done:
        new_line = re.sub(r"- \[ \]", "- [x]", line, count=1)
    else:
        new_line = re.sub(r"- \[x\]", "- [ ]", line, count=1, flags=re.IGNORECASE)
    sections[key][idx] = new_line
    get_today_path(person).write_text(_serialize(sections))
    sync.push(f"{person}: toggle task #{n}")
    task_text = re.sub(r"\s*- \[.\]\s*", "", new_line).strip()
    return key, task_text


def clear_done(person: str) -> int:
    sections = read_tasks(person)
    count = 0
    for key in ("no_sleep", "best_effort"):
        before = len(sections[key])
        sections[key] = [l for l in sections[key] if not re.match(r"\s*- \[x\]", l, re.IGNORECASE)]
        count += before - len(sections[key])
    get_today_path(person).write_text(_serialize(sections))
    sync.push(f"{person}: clear done")
    return count
