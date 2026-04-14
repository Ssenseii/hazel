# Hazel -- Photo Organizer

Hazel is a local tool for photographers that takes a messy folder of photo dumps
and organizes them into a clean, dated archive grouped by shoot.

It reads the date and time each photo was taken (from EXIF metadata, or the file
date as a fallback), groups nearby shots into sessions, and moves or copies them
into a structured folder tree. Nothing is touched until you confirm.

---

## What it does

Given an import folder full of unsorted photos, Hazel produces an export folder
structured like this:

```
export/
  2024/
    June/
      2024-06-14_session-001/
        raw/
          IMG_0001.CR2
          IMG_0002.CR2
        image/
          IMG_0001.JPG
          IMG_0002.JPG
      2024-06-14_session-002/
        image/
          IMG_0045.JPG
    August/
      2024-08-03_session-001/
        video/
          CLIP_001.MP4
        image/
          STILL_001.JPG
```

Sessions are groups of photos taken within a configurable time window of each
other (default: 45 minutes). A gap longer than that starts a new session.

---

## Requirements

- Python 3.10 or later
- Dependencies listed in `requirements.txt`

Install dependencies:

```
pip install -r requirements.txt
```

---

## Getting started

Run Hazel without any arguments to open the interactive menu:

```
python main.py
```

On first launch, Hazel will ask you to pick an import folder and an export folder.
Your choices are saved to `config.yaml` and remembered on the next run.

From the menu you can:

- **Preview** -- scan your photos and show the folder layout without moving anything
- **Move** -- organize and move files into the export folder
- **Copy** -- organize and copy files, leaving originals in place
- **Revert** -- undo the last Move operation
- **Settings** -- change folders, session gap, and other options
- **Help** -- in-app guide to how Hazel works

Always run Preview first so you can review the layout before committing.

---

## CLI usage

Hazel also has a command-line interface for scripting and automation.

**Dry-run preview (default):**
```
python main.py run
```

**Preview with custom folders:**
```
python main.py run --import-dir /path/to/photos --export-dir /path/to/archive
```

**Apply (move files):**
```
python main.py run --apply
```

**Apply using a config file:**
```
python main.py run --config config.yaml --apply
```

**Copy instead of move (originals kept):**
```
python main.py run --copy --apply
```

**Skip confirmation prompt (for scripts):**
```
python main.py run --apply --yes
```

**Override session gap:**
```
python main.py run --gap 60 --apply
```

**Preview and revert the last operation:**
```
python main.py revert
```

**Apply a revert:**
```
python main.py revert --apply
```

---

## Configuration

Settings are stored in `config.yaml` in the same directory as `main.py`.
The file is created automatically on first run. You can also edit it by hand.

```yaml
import: "/photos/import"
export: "/photos/archive"

structure:
  pattern: "{year}/{month}/{session}"

session:
  gap_minutes: 45     # minutes between shots that starts a new session
  min_files: 1        # minimum files required to form a session

naming:
  session_format: "{date}_session-{index:03d}"
  date_format: "%Y-%m-%d"

types:
  separate: true      # sort RAW, image, and video into subfolders
  map:
    raw:   ["cr2", "nef", "arw", "dng", "raf", "orf", "rw2", "sr2"]
    image: ["jpg", "jpeg", "png", "tif", "tiff", "heic", "webp"]
    video: ["mp4", "mov", "avi", "mkv", "mts", "m2ts"]

filters:
  ignore_extensions: ["xmp", "tmp", "thm", "db"]

behavior:
  on_conflict: "rename"   # rename | skip | overwrite
```

### Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `import` | `import` | Folder to scan for photos |
| `export` | `export` | Folder to write the organised archive into |
| `structure.pattern` | `{year}/{month}/{session}` | Top-level folder structure |
| `session.gap_minutes` | `45` | Minutes between shots that starts a new session |
| `session.min_files` | `1` | Files needed to keep a session (others are skipped) |
| `naming.session_format` | `{date}_session-{index:03d}` | Session folder name template |
| `naming.date_format` | `%Y-%m-%d` | Date string format used in folder names |
| `types.separate` | `true` | Sort RAW, image, and video into subfolders |
| `filters.ignore_extensions` | `["xmp", "tmp", ...]` | Extensions to skip entirely |
| `behavior.on_conflict` | `rename` | What to do if a file already exists at the destination |

**on_conflict options:**

- `rename` -- keep both files, add `_1`, `_2` suffix to the new one
- `skip` -- leave the existing file untouched
- `overwrite` -- replace the existing file

---

## Supported file types

**RAW:** CR2, NEF, ARW, DNG, RAF, ORF, RW2, SR2

**Image:** JPG, JPEG, PNG, TIF, TIFF, HEIC, WEBP

**Video:** MP4, MOV, AVI, MKV, MTS, M2TS

Files with any other extension are still organised but placed in an `other`
subfolder when type separation is enabled.

---

## Guidelines

**Run Preview before every real operation.** The preview costs nothing and shows
the exact folder layout Hazel will build. Surprises are easier to fix before
files have moved.

**Use Copy if you are unsure.** Copy leaves your originals exactly where they
are and builds the archive alongside them. You can delete the originals later
once you are happy with the result.

**Adjust the session gap to match how you shoot.** If you shoot events that
span several hours with breaks in between, a larger gap (90-120 min) will keep
related shots together. If you shoot rapid bursts at different locations, a
smaller gap (15-30 min) gives you more granular sessions.

**Do not run Hazel on files that are already organized.** The import folder
should be a raw dump of new photos, not an existing archive. Running it twice
on the same files can create unexpected duplicates or renaming chains depending
on your conflict setting.

**Revert only undoes the last Move.** If you have run Move more than once, only
the most recent operation can be reverted. Revert does not apply to Copy
operations, since the originals were never moved.

**config.yaml is plain text.** If the interactive settings feel limiting, open
`config.yaml` in any text editor. Changes take effect the next time you run
Hazel.

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point, interactive menu, CLI commands |
| `config.py` | Config loading, saving, defaults, validation |
| `scanner.py` | Recursive file scan and EXIF metadata extraction |
| `sessions.py` | Session grouping algorithm |
| `organizer.py` | Destination path computation and file move/copy logic |
| `config.yaml` | Your saved settings (created on first run) |
| `.hazel_revert.json` | Revert log written after each Move (auto-managed) |
| `script.log` | Debug log for the current session |
