"""
sessions.py — Time-proximity session detection.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from scanner import FileInfo


# ─── Data Model ───────────────────────────────────────────────────────────────

@dataclass
class Session:
    index: int              # 1-based index within the same date
    date: datetime          # representative date (earliest file)
    files: list[FileInfo] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


# ─── Algorithm ────────────────────────────────────────────────────────────────

def group(
    files: list[FileInfo],
    gap_minutes: float,
    min_files: int,
) -> list[Session]:
    """
    Group files into sessions based on time proximity.

    Rules:
    - Files must be sorted by capture_time (scanner guarantees this).
    - A new session starts when the gap to the previous file exceeds gap_minutes.
    - Sessions with fewer than min_files files are discarded (files are dropped).
    - Session index is 1-based and restarts per calendar date.

    Returns a list of Session objects sorted by date.
    """
    if not files:
        return []

    gap = timedelta(minutes=gap_minutes)
    raw_sessions: list[list[FileInfo]] = []
    current: list[FileInfo] = [files[0]]

    for file in files[1:]:
        if file.capture_time - current[-1].capture_time > gap:
            raw_sessions.append(current)
            current = [file]
        else:
            current.append(file)
    raw_sessions.append(current)

    # Filter min_files and assign per-date index
    # Track index per calendar date string
    date_counters: dict[str, int] = {}
    sessions: list[Session] = []

    for raw in raw_sessions:
        if len(raw) < min_files:
            continue

        rep_date = raw[0].capture_time
        date_key = rep_date.strftime("%Y-%m-%d")
        date_counters[date_key] = date_counters.get(date_key, 0) + 1
        idx = date_counters[date_key]

        sessions.append(Session(index=idx, date=rep_date, files=raw))

    return sessions
