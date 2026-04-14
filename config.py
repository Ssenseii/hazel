"""
config.py — Config loading, defaults, and validation.
"""

import copy
import os
import yaml

# ─── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_CONFIG: dict = {
    "import": "import",
    "export": "export",
    "structure": {
        "pattern": "{year}/{month}/{date}",
    },
    "session": {
        "gap_minutes": 45,
        "min_files": 1,
    },
    "naming": {
        "session_format": "{date}_session-{index:03d}",
        "date_format": "%Y-%B-%d",
    },
    "types": {
        "separate": True,
        "map": {
            "raw":   ["cr2", "nef", "arw", "dng", "raf", "orf", "rw2", "sr2"],
            "image": ["jpg", "jpeg", "png", "tif", "tiff", "heic", "webp"],
            "video": ["mp4", "mov", "avi", "mkv", "mts", "m2ts"],
        },
    },
    "filters": {
        "ignore_extensions": ["xmp", "tmp", "thm", "db"],
    },
    "behavior": {
        "dry_run": True,
        "on_conflict": "rename",  # rename | skip | overwrite
    },
}

EXAMPLE_CONFIG = """\
import: "/photos/import"
export: "/photos/export"

structure:
  pattern: "{year}/{month}/{date}"

session:
  gap_minutes: 45
  min_files: 1

naming:
  session_format: "{date}_session-{index:03d}"
  date_format: "%Y-%B-%d"

types:
  separate: true
  map:
    raw:   ["cr2", "nef", "arw", "dng", "raf", "orf", "rw2"]
    image: ["jpg", "jpeg", "png", "tif", "tiff", "heic", "webp"]
    video: ["mp4", "mov", "avi", "mkv", "mts", "m2ts"]

filters:
  ignore_extensions: ["xmp", "tmp", "thm", "db"]

behavior:
  dry_run: true
  on_conflict: "rename"   # rename | skip | overwrite
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ─── Public API ───────────────────────────────────────────────────────────────

def load(path: str | None) -> dict:
    """
    Load config from a YAML file and merge with defaults.
    If path is None, returns defaults only.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    if path is None:
        return cfg

    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    cfg = _deep_merge(cfg, raw)
    return cfg


def validate(cfg: dict) -> list[str]:
    """
    Return a list of error strings. Empty list = valid.
    """
    errors: list[str] = []

    if not cfg.get("import"):
        errors.append("'import' path is required.")
    elif not os.path.isdir(cfg["import"]):
        errors.append(f"Import directory does not exist: {cfg['import']!r}")

    if not cfg.get("export"):
        errors.append("'export' path is required.")
    # export dir will be created on apply, so only validate the value exists

    on_conflict = cfg["behavior"].get("on_conflict", "rename")
    if on_conflict not in ("rename", "skip", "overwrite"):
        errors.append(f"behavior.on_conflict must be rename|skip|overwrite, got: {on_conflict!r}")

    gap = cfg["session"].get("gap_minutes", 45)
    if not isinstance(gap, (int, float)) or gap <= 0:
        errors.append("session.gap_minutes must be a positive number.")

    return errors


def save(cfg: dict, path: str = "config.yaml") -> None:
    """Write cfg to a YAML file so settings persist between sessions."""
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)


def extension_to_type(ext: str, cfg: dict) -> str:
    """
    Map a file extension to a type label (raw/image/video/other).
    ext should be lowercase without the leading dot.
    """
    ext = ext.lower().lstrip(".")
    for label, extensions in cfg["types"]["map"].items():
        if ext in [e.lower() for e in extensions]:
            return label
    return "other"
