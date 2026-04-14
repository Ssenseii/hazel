#!/usr/bin/env python3
"""
Hazel -- Photo Organizer
-------------------------
python main.py            interactive menu (default)
python main.py run        dry-run via CLI
python main.py run --apply  apply via CLI
"""

import itertools
import os
import sys
import logging
import signal
import threading
import time

# Ensure UTF-8 output on Windows (cp1252 can't encode box-drawing / symbols)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import click
import questionary
import pyfiglet
from colorama import init, Fore, Style

import config as cfg_mod
import scanner
import sessions as sess_mod
import organizer

# ─── Init ─────────────────────────────────────────────────────────────────────

init(autoreset=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("script.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─── Display Helpers ──────────────────────────────────────────────────────────

WIDTH = 60
STYLE = questionary.Style([
    ("selected",    "fg:cyan bold"),
    ("pointer",     "fg:cyan bold"),
    ("highlighted", "fg:cyan"),
])


def banner():
    art = pyfiglet.figlet_format("HAZEL", font="big")
    print(Fore.CYAN + Style.BRIGHT + art, end="")
    print(Fore.WHITE + Style.BRIGHT + "  Photo Organizer  " + Fore.CYAN + "|" + Fore.WHITE + "  Ctrl+C to quit")
    divider()


def divider():
    print(Fore.CYAN + Style.DIM + "-" * WIDTH)


def section(title: str):
    print()
    divider()
    print(Fore.CYAN + Style.BRIGHT + f"  {title}")
    divider()


def ok(msg: str):
    print(Fore.GREEN + Style.BRIGHT + f"  +  {msg}")
    logger.info("OK  -- %s", msg)


def err(msg: str):
    print(Fore.RED + Style.BRIGHT + f"  x  {msg}")
    logger.error("ERR -- %s", msg)


def warn(msg: str):
    print(Fore.YELLOW + Style.BRIGHT + f"  !  {msg}")
    logger.warning("WARN -- %s", msg)


def info(msg: str):
    print(Fore.YELLOW + f"  ->  {msg}")
    logger.info("INFO -- %s", msg)


def dim(msg: str):
    print(Fore.WHITE + Style.DIM + f"      {msg}")


def blank():
    print()


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _count_media_files(folder: str, cfg: dict) -> int:
    """Quick count of recognisable media files — extensions only, no EXIF."""
    if not os.path.isdir(folder):
        return 0
    known_exts: set[str] = set()
    for exts in cfg["types"]["map"].values():
        known_exts.update(e.lower() for e in exts)
    count = 0
    try:
        for _, _, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lstrip(".").lower() in known_exts:
                    count += 1
    except PermissionError:
        pass
    return count


def _open_folder(path: str) -> None:
    """Open a folder in the OS file manager (Explorer / Finder / xdg-open)."""
    import subprocess
    import platform
    try:
        if platform.system() == "Windows":
            os.startfile(os.path.normpath(path))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        warn(f"Could not open folder: {exc}")


def _print_preview_tree(sessions, cfg: dict) -> None:
    """Display sessions grouped by year/month as a readable table."""
    from collections import defaultdict

    naming  = cfg["naming"]
    export  = cfg["export"]

    info(f"Export root: {export}")
    blank()

    groups: dict[tuple, list] = defaultdict(list)
    for s in sessions:
        key = (s.date.strftime("%Y"), s.date.strftime("%B"))
        groups[key].append(s)

    for (year, month), sess_list in sorted(groups.items()):
        print(Fore.CYAN + Style.BRIGHT + f"  {year} / {month}")

        for s in sess_list:
            date_str  = s.date.strftime(naming.get("date_format", "%Y-%m-%d"))
            fmt       = naming.get("session_format", "{date}_session-{index:03d}")
            sess_name = fmt.format(date=date_str, index=s.index)

            span_start = s.date.strftime("%H:%M")
            span_end   = s.files[-1].capture_time.strftime("%H:%M")

            type_counts: dict[str, int] = defaultdict(int)
            for f in s.files:
                type_counts[f.file_type] += 1
            type_str = "  ".join(f"{t}:{c}" for t, c in sorted(type_counts.items()))

            print(
                Fore.WHITE + Style.DIM  + f"    {sess_name:<44}"
                + Fore.WHITE            + f"  {span_start}-{span_end}"
                + Style.DIM             + f"  {s.file_count:>4} files"
                + "    " + type_str
            )

        blank()


# ─── Spinner ─────────────────────────────────────────────────────────────────

class _Spinner:
    """Animated terminal spinner for blocking operations."""
    _FRAMES = ["-", "\\", "|", "/"]

    def __init__(self, msg: str):
        self._msg    = msg
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        pad = " " * 6
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(
                Fore.CYAN + f"\r  {frame}  " + Fore.WHITE + Style.DIM + self._msg + pad
            )
            sys.stdout.flush()
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * (len(self._msg) + 12) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()


# ─── Help / About ─────────────────────────────────────────────────────────────

def _show_help() -> None:
    section("Help -- How Hazel Works")

    print(Fore.WHITE + Style.BRIGHT + "  What Hazel does")
    print(Fore.WHITE + Style.DIM + """
  Hazel looks at your photos, reads the date and time each one
  was taken, groups them into shoots, then copies or moves them
  into a tidy folder structure like:

      2024 / June / 2024-June-14_session-001 / raw /
                                             / image /
      2024 / June / 2024-June-14_session-002 / image /
  """)

    divider()
    print(Fore.WHITE + Style.BRIGHT + "  Key concepts")
    print(Fore.WHITE + Style.DIM + """
  SESSION  A group of photos taken close together in time.
           If there's a gap longer than the session gap (default:
           45 min) between shots, Hazel treats that as a new shoot.

  IMPORT   The folder where your photos are right now -- an SD
           card, camera download folder, or phone backup.

  EXPORT   The folder Hazel will organise everything into.
           Your originals stay untouched until you choose Move.

  PREVIEW  Always safe -- shows exactly what would happen without
           touching any files.

  REVERT   Undoes the last Move so you can start over if needed.
  """)

    divider()
    print(Fore.WHITE + Style.BRIGHT + "  Tips")
    print(Fore.WHITE + Style.DIM + """
  * Run Preview first so you can see the folder layout before
    committing. Nothing moves until you choose Move or Copy.

  * Use Copy if you want to keep originals exactly where they
    are and build a separate organised archive.

  * If your shoots often span several hours in one location,
    increase the Session Gap in Settings.

  * Settings are saved to config.yaml in the same folder as
    Hazel, so your folders and preferences are remembered.
  """)

    blank()
    questionary.press_any_key_to_continue("  Press any key to go back...").ask()


# ─── Folder Picker ────────────────────────────────────────────────────────────

def _questionary_folder_browser(prompt: str, start: str = "") -> str | None:
    """Keyboard-driven folder browser using questionary as a fallback picker."""
    import platform

    current = os.path.abspath(start) if start and os.path.isdir(start) else os.path.abspath(os.getcwd())

    while True:
        try:
            subdirs = sorted(
                d for d in os.listdir(current)
                if os.path.isdir(os.path.join(current, d)) and not d.startswith(".")
            )
        except PermissionError:
            subdirs = []

        at_root = os.path.dirname(current) == current

        choices = [questionary.Choice(f"[Select]  {current}", value="__select__")]

        if not at_root:
            choices.append(questionary.Choice("..  (go up)", value="__up__"))

        # On Windows at a drive root, offer to switch drives
        if platform.system() == "Windows" and at_root:
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            if len(drives) > 1:
                choices.append(questionary.Choice("Switch drive...", value="__drives__"))

        for d in subdirs:
            choices.append(questionary.Choice(d + "/", value=d))

        choices.append(questionary.Separator())
        choices.append(questionary.Choice("Cancel", value="__cancel__"))

        blank()
        print(Fore.CYAN + Style.DIM + f"  {current}")
        selection = questionary.select(prompt, choices=choices, style=STYLE).ask()

        if selection is None or selection == "__cancel__":
            return None
        elif selection == "__select__":
            return current
        elif selection == "__up__":
            current = os.path.dirname(current)
        elif selection == "__drives__":
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            drive = questionary.select("Select drive:", choices=drives, style=STYLE).ask()
            if drive:
                current = drive
        else:
            current = os.path.join(current, selection)


def pick_folder(prompt: str, default: str = "") -> str | None:
    """
    Open a native OS folder-picker dialog.
    Falls back to a keyboard-driven questionary browser if tkinter is unavailable
    or no display is present (e.g. SSH sessions).
    Returns the selected path, or None if the user cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        result = filedialog.askdirectory(
            title=prompt,
            initialdir=default if default and os.path.isdir(default) else os.getcwd(),
        )
        root.destroy()
        # Empty string means the user dismissed the dialog — respect that as a cancel
        return os.path.normpath(result) if result else None
    except Exception:
        pass

    # tkinter unavailable (no display, headless, etc.) — use terminal browser
    info("Native folder picker unavailable, opening terminal browser...")
    return _questionary_folder_browser(prompt, start=default)


# ─── Graceful Exit ────────────────────────────────────────────────────────────

def _exit(sig=None, frame=None):
    blank()
    print(Fore.YELLOW + Style.BRIGHT + "  Goodbye!\n")
    logger.info("Tool exited by user")
    sys.exit(0)


signal.signal(signal.SIGINT, _exit)


# ─── Core Logic (shared by interactive + CLI) ─────────────────────────────────

def run_organize(cfg: dict, dry_run: bool, mode: str = "move") -> dict | None:
    """
    Run the full scan -> session -> preview -> (optional apply) pipeline.
    Returns the summary dict, or None if aborted / nothing to do.
    dry_run=True   prints preview only.
    dry_run=False  moves or copies files depending on mode ("move" | "copy").
    """
    errors = cfg_mod.validate(cfg)
    if errors:
        blank()
        for e in errors:
            err(e)
        return None

    # Scan
    section("Scanning")
    info(f"Import:  {cfg['import']}")
    info(f"Export:  {cfg['export']}")
    if dry_run:
        warn("DRY RUN -- nothing will be moved or copied")

    with _Spinner("Scanning photos..."):
        files = scanner.scan(cfg["import"], cfg["filters"]["ignore_extensions"])

    if not files:
        warn("No files found in import folder.")
        return None

    total_size = sum(f.size for f in files)
    exif_count = sum(1 for f in files if f.exif_source == "exif")
    ok(f"Found {len(files)} files  ({_fmt_bytes(total_size)})")
    info(f"Date from photo metadata: {exif_count}   Estimated from file date: {len(files) - exif_count}")

    for f in files:
        f.file_type = cfg_mod.extension_to_type(f.ext, cfg)

    # Sessions
    section("Sessions")
    sessions = sess_mod.group(
        files=files,
        gap_minutes=cfg["session"]["gap_minutes"],
        min_files=cfg["session"]["min_files"],
    )

    files_in_sessions = sum(s.file_count for s in sessions)
    dropped = len(files) - files_in_sessions

    ok(f"Detected {len(sessions)} session(s)")
    info(f"A session = photos taken within {cfg['session']['gap_minutes']:.0f} minutes of each other.")
    if dropped:
        warn(f"Skipped {dropped} file(s) -- too few photos to form a shoot (minimum: {cfg['session']['min_files']})")

    blank()
    for s in sessions:
        session_name = f"{s.date.strftime(cfg['naming']['date_format'])}_session-{s.index:03d}"
        span_start = s.date.strftime("%H:%M")
        span_end   = s.files[-1].capture_time.strftime("%H:%M")
        dim(f"{session_name}   ({s.file_count} files,  {span_start}-{span_end})")

    # Preview
    section("Preview")
    ops = organizer.compute(sessions, cfg)
    on_conflict = cfg["behavior"].get("on_conflict", "rename")

    _print_preview_tree(sessions, cfg)

    # Copy size warning — ask before committing if payload is large
    _GB = 1024 ** 3
    if not dry_run and mode == "copy" and total_size > _GB:
        blank()
        warn(f"You are about to COPY {_fmt_bytes(total_size)} of files (originals stay in place).")
        confirmed = questionary.confirm(
            f"Copy {_fmt_bytes(total_size)} to '{cfg['export']}'?",
            default=False,
            style=STYLE,
        ).ask()
        if not confirmed:
            info("Cancelled.")
            return None

    # Apply
    section("Result")
    if dry_run:
        summary = organizer.apply(ops, dry_run=True, on_conflict=on_conflict, mode=mode)
    else:
        verb_ing = "Copying" if mode == "copy" else "Moving"
        total_ops = len(ops)

        def _progress(done: int, total: int) -> None:
            sys.stdout.write(
                Fore.YELLOW + f"\r  ->  {verb_ing} files...  {done} / {total}  "
            )
            sys.stdout.flush()
            if done == total:
                sys.stdout.write("\r" + " " * 50 + "\r")
                sys.stdout.flush()

        summary = organizer.apply(ops, dry_run=False, on_conflict=on_conflict, mode=mode, on_progress=_progress)

    verb = "previewed" if dry_run else ("copied" if mode == "copy" else "moved")
    ok(f"Files {verb}:  {summary['moved']}")
    if summary["renamed"]:
        info(f"Renamed (conflict):  {summary['renamed']}")
    if summary["skipped"]:
        info(f"Skipped (conflict):  {summary['skipped']}")
    if summary["overwritten"]:
        warn(f"Overwritten:         {summary['overwritten']}")
    for e in summary["errors"]:
        err(e)

    if dry_run:
        blank()
        warn("This was a preview. Go back and choose Move or Copy to organize files.")
    elif mode == "copy":
        blank()
        ok(f"Done. Copied into: {cfg['export']}  (originals untouched)")
    else:
        organizer.save_revert_log(ops)
        blank()
        ok(f"Done. Organized into: {cfg['export']}")

    logger.info("Run complete: %s", summary)
    blank()
    return summary


# ─── Revert ───────────────────────────────────────────────────────────────────

def run_revert() -> None:
    """Preview and optionally apply a revert of the last operation."""
    log = organizer.load_revert_log()
    if log is None:
        blank()
        warn("No previous operation to revert.")
        return

    section("Revert")
    info(f"Last operation : {log['timestamp']}")
    info(f"Files to restore: {log['count']}")
    blank()

    for entry in log["ops"][:12]:
        src_short = os.path.basename(entry["destination"])
        dim(f"{src_short:<30}  ->  {entry['source']}")
    if len(log["ops"]) > 12:
        info(f"... and {len(log['ops']) - 12} more files")

    blank()
    confirmed = questionary.confirm(
        "Move files back to their original locations?",
        default=False,
        style=STYLE,
    ).ask()
    if not confirmed:
        info("Cancelled.")
        return

    summary = organizer.revert(dry_run=False)
    section("Result")
    ok(f"Restored: {summary['restored']}")
    if summary["skipped"]:
        warn(f"Skipped (file not found): {summary['skipped']}")
    for e in summary["errors"]:
        err(e)
    blank()
    if not summary["errors"]:
        ok("Revert complete.")
    logger.info("Revert complete: %s", summary)
    blank()


# ─── Settings Submenu ─────────────────────────────────────────────────────────

def menu_settings(cfg: dict):
    """Let the user tweak the live config dict and auto-save changes to disk."""
    while True:
        blank()
        divider()
        print(Fore.CYAN + Style.BRIGHT + "  Settings")
        divider()
        info(f"Import folder   : {cfg['import']}")
        info(f"Export folder   : {cfg['export']}")
        info(f"Session gap     : {cfg['session']['gap_minutes']} min  (gap between shots that starts a new shoot)")
        info(f"Sort by type    : {'Yes' if cfg['types']['separate'] else 'No'}  (RAW / photo / video subfolders)")
        info(f"Duplicate files : {cfg['behavior']['on_conflict']}")
        blank()

        choice = questionary.select(
            "What do you want to change?",
            choices=[
                questionary.Choice("Import folder  -- where your photos are now",              value="import"),
                questionary.Choice("Export folder  -- where organised photos will go",         value="export"),
                questionary.Choice("Session gap    -- minutes gap between shots = new shoot",  value="gap"),
                questionary.Choice("Sort by type   -- separate RAW / photo / video folders",   value="separate"),
                questionary.Choice("Duplicate files -- what to do if a file already exists",   value="conflict"),
                questionary.Choice("Back",                                                       value="back"),
            ],
            style=STYLE,
        ).ask()

        if choice is None or choice == "back":
            return

        if choice == "import":
            info(f"Currently: {cfg['import']}")
            val = pick_folder("Select import folder", default=cfg["import"])
            if val:
                cfg["import"] = val
                cfg_mod.save(cfg, _CONFIG_FILE)
                dim("Saved.")

        elif choice == "export":
            info(f"Currently: {cfg['export']}")
            val = pick_folder("Select export folder", default=cfg["export"])
            if val:
                cfg["export"] = val
                cfg_mod.save(cfg, _CONFIG_FILE)
                dim("Saved.")

        elif choice == "gap":
            preset = questionary.select(
                "How long a gap between shots means it's a new shoot? (default: 45 min)",
                choices=[
                    questionary.Choice("15 min  – rapid bursts / same scene",  value=15),
                    questionary.Choice("30 min",                                value=30),
                    questionary.Choice("45 min  (default)",                     value=45),
                    questionary.Choice("1 hour",                                value=60),
                    questionary.Choice("2 hours",                               value=120),
                    questionary.Choice("Custom...",                             value="custom"),
                ],
                style=STYLE,
            ).ask()
            if preset == "custom":
                val = questionary.text(
                    "Session gap in minutes:",
                    default=str(cfg["session"]["gap_minutes"]),
                    validate=lambda v: v.replace(".", "", 1).isdigit() and float(v) > 0 or "Must be a positive number.",
                    style=STYLE,
                ).ask()
                if val:
                    cfg["session"]["gap_minutes"] = float(val)
                    cfg_mod.save(cfg, _CONFIG_FILE)
                    dim("Saved.")
            elif preset is not None:
                cfg["session"]["gap_minutes"] = float(preset)
                cfg_mod.save(cfg, _CONFIG_FILE)
                dim("Saved.")

        elif choice == "separate":
            val = questionary.confirm(
                "Put RAW, photo, and video files into separate subfolders?",
                default=cfg["types"]["separate"],
                style=STYLE,
            ).ask()
            if val is not None:
                cfg["types"]["separate"] = val
                cfg_mod.save(cfg, _CONFIG_FILE)
                dim("Saved.")

        elif choice == "conflict":
            val = questionary.select(
                "What should Hazel do if a file with the same name already exists?",
                choices=[
                    questionary.Choice("Keep both  -- rename the new file (_1, _2 ...)",  value="rename"),
                    questionary.Choice("Skip       -- leave the existing file as-is",      value="skip"),
                    questionary.Choice("Replace    -- overwrite the existing file",        value="overwrite"),
                ],
                style=STYLE,
            ).ask()
            if val:
                cfg["behavior"]["on_conflict"] = val
                cfg_mod.save(cfg, _CONFIG_FILE)
                dim("Saved.")


# ─── First-run Wizard ─────────────────────────────────────────────────────────

def _first_run_wizard(cfg: dict) -> None:
    """Guide a brand-new user through picking import and export folders."""
    section("Welcome to Hazel!")
    info("Hazel sorts your photos into dated folders, grouped by shoot.")
    info("Let's pick two folders to get started.")
    blank()
    info("IMPORT  --  where your photos are right now")
    info("            (e.g. SD card, camera download folder, phone backup)")
    val = pick_folder("Select your IMPORT folder", default="")
    if val:
        cfg["import"] = val
    blank()
    info("EXPORT  --  where Hazel will put the organised photos")
    info("            (e.g. your Photos library, an external hard drive)")
    val = pick_folder("Select your EXPORT folder", default="")
    if val:
        cfg["export"] = val
    blank()
    ok("Folders set. You can change them any time via Settings.")


# ─── Interactive Main Menu ────────────────────────────────────────────────────

_CONFIG_FILE = "config.yaml"


def interactive_menu():
    """The primary interface. Runs as a loop until the user exits."""
    cfg = cfg_mod.load(_CONFIG_FILE if os.path.isfile(_CONFIG_FILE) else None)

    # First-run: guide user to pick folders when defaults are still in place
    if cfg["import"] == "import" and cfg["export"] == "export":
        _first_run_wizard(cfg)
        cfg_mod.save(cfg, _CONFIG_FILE)
        ok("Settings saved to config.yaml.")

    while True:
        blank()
        # ── Status line ──────────────────────────────────────────────────────
        file_count = _count_media_files(cfg["import"], cfg)
        if file_count:
            count_str = f"{file_count} photo/video file{'s' if file_count != 1 else ''} ready"
        elif os.path.isdir(cfg["import"]):
            count_str = "no photos found in this folder"
        else:
            count_str = "folder not found -- check Settings"
        print(Fore.CYAN + Style.BRIGHT  + "  Import : " + Fore.WHITE + cfg["import"])
        print(Fore.WHITE + Style.DIM    + f"           {count_str}")
        print(Fore.CYAN + Style.BRIGHT  + "  Export : " + Fore.WHITE + cfg["export"])
        divider()
        # ─────────────────────────────────────────────────────────────────────
        choice = questionary.select(
            "What do you want to do?",
            choices=[
                questionary.Choice("Preview    -- scan and show what would move",         value="preview"),
                questionary.Choice("Move       -- organize and move files to export",      value="move"),
                questionary.Choice("Copy       -- organize and copy (originals kept)",     value="copy"),
                questionary.Choice("Revert     -- undo the last move operation",           value="revert"),
                questionary.Choice("Settings   -- change folders / options",               value="settings"),
                questionary.Choice("Help       -- how Hazel works, key concepts and tips", value="help"),
                questionary.Choice("Exit",                                                  value="exit"),
            ],
            style=STYLE,
        ).ask()

        if choice is None or choice == "exit":
            _exit()

        elif choice == "settings":
            menu_settings(cfg)

        elif choice == "help":
            _show_help()

        elif choice == "revert":
            run_revert()

        elif choice == "preview":
            run_organize(cfg, dry_run=True)

        elif choice == "move":
            blank()
            confirmed = questionary.confirm(
                f"Move files from '{cfg['import']}' into '{cfg['export']}'?",
                default=False,
                style=STYLE,
            ).ask()
            if confirmed:
                result = run_organize(cfg, dry_run=False, mode="move")
                if result:
                    blank()
                    if questionary.confirm("Open the export folder now?", default=True, style=STYLE).ask():
                        _open_folder(cfg["export"])
            else:
                info("Cancelled.")

        elif choice == "copy":
            blank()
            confirmed = questionary.confirm(
                f"Copy files from '{cfg['import']}' into '{cfg['export']}' (originals kept)?",
                default=False,
                style=STYLE,
            ).ask()
            if confirmed:
                result = run_organize(cfg, dry_run=False, mode="copy")
                if result:
                    blank()
                    if questionary.confirm("Open the export folder now?", default=True, style=STYLE).ask():
                        _open_folder(cfg["export"])
            else:
                info("Cancelled.")


# ─── CLI (secondary interface) ────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Hazel -- photo organizer. Run without arguments for interactive mode."""
    banner()
    if ctx.invoked_subcommand is None:
        interactive_menu()


@cli.command("run")
@click.option("--apply",      is_flag=True,  default=False, help="Move files (default: dry-run preview).")
@click.option("--yes", "-y",  is_flag=True,  default=False, help="Skip confirmation prompt.")
@click.option("--config",     "config_path", default=None,  metavar="FILE",  help="Path to YAML config.")
@click.option("--import-dir", "import_dir",  default=None,  metavar="DIR",   help="Override import folder.")
@click.option("--export-dir", "export_dir",  default=None,  metavar="DIR",   help="Override export folder.")
@click.option("--gap",        "gap_minutes", default=None,  type=float, metavar="MINS", help="Session gap in minutes (overrides config).")
@click.option("--copy",       "copy_mode",   is_flag=True,  default=False,              help="Copy files instead of moving them (originals kept).")
def cmd_run(apply: bool, yes: bool, config_path: str | None, import_dir: str | None, export_dir: str | None, gap_minutes: float | None, copy_mode: bool):
    """Scan and organize photos via CLI flags."""
    try:
        cfg = cfg_mod.load(config_path)
    except FileNotFoundError as exc:
        err(str(exc))
        sys.exit(1)

    if import_dir:
        cfg["import"] = import_dir
    if export_dir:
        cfg["export"] = export_dir
    if gap_minutes is not None:
        cfg["session"]["gap_minutes"] = gap_minutes

    mode    = "copy" if copy_mode else "move"
    dry_run = not apply

    if apply and not yes:
        blank()
        action = "Copy" if copy_mode else "Move"
        confirmed = questionary.confirm(
            f"{action} files from '{cfg['import']}' into '{cfg['export']}'?",
            default=False,
            style=STYLE,
        ).ask()
        if not confirmed:
            info("Aborted.")
            sys.exit(0)

    result = run_organize(cfg, dry_run=dry_run, mode=mode)
    if result is None:
        sys.exit(1)


@cli.command("revert")
@click.option("--apply",     is_flag=True, default=False, help="Actually revert (default: dry-run preview).")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
def cmd_revert(apply: bool, yes: bool):
    """Undo the last organize operation, moving files back to their original locations."""
    log = organizer.load_revert_log()
    if log is None:
        warn("No previous operation to revert.")
        sys.exit(1)

    section("Revert")
    info(f"Last operation : {log['timestamp']}")
    info(f"Files to restore: {log['count']}")
    blank()

    for entry in log["ops"][:12]:
        src_short = os.path.basename(entry["destination"])
        dim(f"{src_short:<30}  ->  {entry['source']}")
    if len(log["ops"]) > 12:
        info(f"... and {len(log['ops']) - 12} more files")

    dry_run = not apply

    if apply and not yes:
        blank()
        confirmed = questionary.confirm(
            "Move files back to their original locations?",
            default=False,
            style=STYLE,
        ).ask()
        if not confirmed:
            info("Aborted.")
            sys.exit(0)

    summary = organizer.revert(dry_run=dry_run)
    section("Result")

    if dry_run:
        ok(f"Would restore: {summary['restored']}")
        if summary["skipped"]:
            warn(f"Not found (would skip): {summary['skipped']}")
        blank()
        warn("This was a preview. Use --apply to restore files.")
    else:
        ok(f"Restored: {summary['restored']}")
        if summary["skipped"]:
            warn(f"Skipped (file not found): {summary['skipped']}")
        for e in summary["errors"]:
            err(e)
        blank()
        if not summary["errors"]:
            ok("Revert complete.")
    logger.info("Revert: %s", summary)
    blank()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
