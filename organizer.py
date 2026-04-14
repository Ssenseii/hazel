"""
organizer.py — Destination computation and file move logic.
"""

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime

import config as cfg_mod
from sessions import Session
from scanner import FileInfo

REVERT_LOG_PATH = ".hazel_revert.json"


# ─── Data Model ───────────────────────────────────────────────────────────────

@dataclass
class MoveOp:
    source: str
    destination: str
    conflict: str = ""   # "" | "rename" | "skip" | "overwrite" — set during apply


# ─── Path Builders ────────────────────────────────────────────────────────────

def _session_name(session: Session, naming: dict) -> str:
    """Build the session folder name from the naming config."""
    date_str = session.date.strftime(naming.get("date_format", "%Y-%m-%d"))
    fmt = naming.get("session_format", "{date}_session-{index:03d}")
    return fmt.format(date=date_str, index=session.index)


def _pattern_path(session: Session, naming: dict, pattern: str) -> str:
    """Expand the structure pattern into a relative path."""
    date = session.date
    parts = {
        "year":    date.strftime("%Y"),
        "month":   date.strftime("%B"),
        "day":     date.strftime("%d"),
        "date":    date.strftime(naming.get("date_format", "%Y-%m-%d")),
        "session": _session_name(session, naming),
    }
    return pattern.format(**parts)


def _type_subfolder(file: FileInfo, cfg: dict) -> str:
    """Return the type subfolder name, or '' if separation is disabled."""
    if not cfg["types"].get("separate", True):
        return ""
    file_type = cfg_mod.extension_to_type(file.ext, cfg)
    return file_type


def _safe_destination(dest: str, on_conflict: str) -> tuple[str, str]:
    """
    Return (final_path, conflict_action) where conflict_action is
    "none", "rename", "skip", or "overwrite".
    """
    if not os.path.exists(dest):
        return dest, "none"

    if on_conflict == "overwrite":
        return dest, "overwrite"

    if on_conflict == "skip":
        return dest, "skip"

    # rename: add _1, _2, ... suffix before the extension
    base, ext = os.path.splitext(dest)
    counter = 1
    candidate = f"{base}_{counter}{ext}"
    while os.path.exists(candidate):
        counter += 1
        candidate = f"{base}_{counter}{ext}"
    return candidate, "rename"


# ─── Public API ───────────────────────────────────────────────────────────────

def compute(sessions: list[Session], cfg: dict) -> list[MoveOp]:
    """
    Compute MoveOp list from sessions.
    Does NOT touch the filesystem.
    """
    export_root = cfg["export"]
    pattern = cfg["structure"]["pattern"]
    naming = cfg["naming"]
    on_conflict = cfg["behavior"].get("on_conflict", "rename")
    ops: list[MoveOp] = []

    for session in sessions:
        rel_base = _pattern_path(session, naming, pattern)

        for file in session.files:
            type_sub = _type_subfolder(file, cfg)
            if type_sub:
                rel_dir = os.path.join(rel_base, type_sub)
            else:
                rel_dir = rel_base

            filename = f"{file.name}.{file.ext}"
            dest = os.path.join(export_root, rel_dir, filename)
            ops.append(MoveOp(source=file.path, destination=dest))

    return ops


def apply(ops: list[MoveOp], dry_run: bool, on_conflict: str, mode: str = "move", on_progress=None) -> dict:
    """
    Execute the move/copy operations.

    mode: "move" (default) or "copy" — copy keeps the originals in place.
    on_progress: optional callable(done: int, total: int) called after each file.

    Returns a summary dict:
      moved, skipped, renamed, overwritten, errors
    """
    summary = {"moved": 0, "skipped": 0, "renamed": 0, "overwritten": 0, "errors": []}
    total = len(ops)

    for i, op in enumerate(ops, 1):
        final_dest, conflict_action = _safe_destination(op.destination, on_conflict)
        op.conflict = conflict_action

        if conflict_action == "skip":
            summary["skipped"] += 1
            continue

        if dry_run:
            # Simulate but don't touch disk
            if conflict_action == "rename":
                summary["renamed"] += 1
            elif conflict_action == "overwrite":
                summary["overwritten"] += 1
            else:
                summary["moved"] += 1
            continue

        # Real apply
        try:
            os.makedirs(os.path.dirname(final_dest), exist_ok=True)
            if mode == "copy":
                shutil.copy2(op.source, final_dest)
            else:
                shutil.move(op.source, final_dest)
            op.destination = final_dest  # update with final resolved path

            if conflict_action == "rename":
                summary["renamed"] += 1
            elif conflict_action == "overwrite":
                summary["overwritten"] += 1
            else:
                summary["moved"] += 1

        except Exception as exc:
            summary["errors"].append(f"{op.source}: {exc}")

        if on_progress:
            on_progress(i, total)

    return summary


# ─── Revert ───────────────────────────────────────────────────────────────────

def save_revert_log(ops: list[MoveOp], path: str = REVERT_LOG_PATH) -> None:
    """Persist a revert log after a real (non-dry) apply."""
    entries = [
        {"source": op.source, "destination": op.destination}
        for op in ops
        if op.conflict != "skip"
    ]
    data = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "count": len(entries),
        "ops": entries,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def load_revert_log(path: str = REVERT_LOG_PATH) -> dict | None:
    """Return the revert log dict, or None if no log exists."""
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def revert(dry_run: bool = True, path: str = REVERT_LOG_PATH) -> dict:
    """
    Reverse the last apply: move each file from its destination back to source.

    Returns a summary dict: restored, skipped, errors.
    Deletes the log after a successful real (non-dry) revert.
    """
    log = load_revert_log(path)
    if log is None:
        return {"restored": 0, "skipped": 0, "errors": ["No revert log found."]}

    summary = {"restored": 0, "skipped": 0, "errors": []}

    for entry in log["ops"]:
        current = entry["destination"]  # where the file is now
        original = entry["source"]      # where it should go back

        if not os.path.isfile(current):
            summary["skipped"] += 1
            continue

        if dry_run:
            summary["restored"] += 1
            continue

        try:
            parent = os.path.dirname(original)
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.move(current, original)
            summary["restored"] += 1
        except Exception as exc:
            summary["errors"].append(f"{current}: {exc}")

    if not dry_run and not summary["errors"]:
        try:
            os.remove(path)
        except OSError:
            pass

    return summary
