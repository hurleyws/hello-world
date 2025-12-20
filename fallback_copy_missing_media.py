import zipfile
import shutil
import subprocess
from pathlib import Path
import datetime

# =========================
# CONFIG
# =========================
ZIP_PATH = Path(r"C:\Users\hurle\google_icloud\TakeoutZips\takeout-20250827T004600Z-1-016.zip")
IMPORT_READY = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\import_ready")
EXIFTOOL = Path(r"C:\Users\hurle\google_icloud\exiftool-13.43_64\exiftool.exe")

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4"}

IMPORT_READY.mkdir(parents=True, exist_ok=True)

# =========================
# Helpers
# =========================

def run_exiftool(args):
    return subprocess.run(args, capture_output=True, text=True)

def apply_folder_year_timestamp(target_path, folder_name):
    parts = folder_name.split()
    year = parts[-1] if parts and parts[-1].isdigit() and len(parts[-1]) == 4 else None

    if not year:
        return

    fallback = f"{year}:01:01 12:00:00"
    fs_fallback = fallback.replace(":", "-", 2)

    ext = target_path.suffix.lower()
    base = [str(EXIFTOOL), "-m", "-overwrite_original"]

    if ext in (".jpg", ".jpeg", ".heic"):
        base += ["-EXIF:all="]
        tags = [
            f"-EXIF:DateTimeOriginal={fallback}",
            f"-EXIF:CreateDate={fallback}",
            f"-IFD0:ModifyDate={fallback}",
        ]
    elif ext == ".png":
        tags = [
            f"-PNG:CreationTime={fallback}",
            f"-XMP:CreateDate={fallback}",
            f"-XMP:ModifyDate={fallback}",
        ]
    elif ext in (".mp4", ".mov"):
        tags = [
            f"-QuickTime:CreateDate={fallback}",
            f"-QuickTime:ModifyDate={fallback}",
        ]
    else:
        return

    run_exiftool(base + tags + [str(target_path)])
    run_exiftool([
        str(EXIFTOOL),
        "-m",
        f"-FileModifyDate={fs_fallback}",
        f"-FileCreateDate={fs_fallback}",
        "-overwrite_original",
        str(target_path)
    ])

# =========================
# MAIN
# =========================

print("🔍 Scanning import_ready...")
existing_stems = {p.stem.lower() for p in IMPORT_READY.iterdir() if p.is_file()}

copied = []

print("📦 Scanning ZIP for missing media...")

with zipfile.ZipFile(ZIP_PATH, "r") as z:
    for member in z.namelist():
        path = Path(member)

        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue

        stem = path.stem.lower()
        if stem in existing_stems:
            continue

        # Skip Google junk
        if "supplemental-metadata" in path.name.lower():
            continue

        print(f"➕ Copying missing media: {path.name}")

        target_path = IMPORT_READY / path.name
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with z.open(member) as src, open(target_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

        apply_folder_year_timestamp(target_path, path.parent.name)
        copied.append(path.name)

print("\n======= FALLBACK SUMMARY =======")
print(f"✅ Newly copied files: {len(copied)}")

if copied:
    for name in copied[:25]:
        print(" -", name)
    if len(copied) > 25:
        print(f"... and {len(copied) - 25} more")

print("\n🎉 Fallback pass complete.")
