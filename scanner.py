"""
scanner.py — Recursive file scan with EXIF metadata extraction.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime

import exifread

# ─── Data Model ───────────────────────────────────────────────────────────────

@dataclass
class FileInfo:
    path: str               # absolute path
    name: str               # filename without extension
    ext: str                # lowercase, no dot  e.g. "jpg"
    size: int               # bytes
    capture_time: datetime  # from EXIF or mtime fallback
    exif_source: str        # "exif" | "mtime"
    file_type: str = ""     # filled in by caller using config


# ─── EXIF Helpers ─────────────────────────────────────────────────────────────

_EXIF_DATE_TAGS = [
    "EXIF DateTimeOriginal",
    "EXIF DateTimeDigitized",
    "Image DateTime",
]
_EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


def _read_exif_time(path: str) -> datetime | None:
    try:
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, stop_tag="EXIF DateTimeOriginal", details=False)
        for tag in _EXIF_DATE_TAGS:
            if tag in tags:
                raw = str(tags[tag]).strip()
                return datetime.strptime(raw, _EXIF_DATE_FORMAT)
    except Exception:
        pass
    return None


def _mtime(path: str) -> datetime:
    return datetime.fromtimestamp(os.path.getmtime(path))


# ─── Public API ───────────────────────────────────────────────────────────────

def scan(import_dir: str, ignore_extensions: list[str]) -> list[FileInfo]:
    """
    Recursively scan import_dir and return a sorted list of FileInfo objects.
    Files whose extension is in ignore_extensions are skipped.
    Result is sorted by capture_time ascending.
    """
    ignored = {e.lower().lstrip(".") for e in ignore_extensions}
    files: list[FileInfo] = []

    for dirpath, _dirnames, filenames in os.walk(import_dir):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            name, dot_ext = os.path.splitext(filename)
            ext = dot_ext.lstrip(".").lower()

            if ext in ignored:
                continue

            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            exif_time = _read_exif_time(full_path)
            if exif_time is not None:
                capture_time = exif_time
                exif_source = "exif"
            else:
                capture_time = _mtime(full_path)
                exif_source = "mtime"

            files.append(FileInfo(
                path=full_path,
                name=name,
                ext=ext,
                size=size,
                capture_time=capture_time,
                exif_source=exif_source,
            ))

    files.sort(key=lambda f: f.capture_time)
    return files
