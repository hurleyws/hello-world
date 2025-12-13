import json
import zipfile
import shutil
import subprocess
import datetime
from pathlib import Path
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

# =========================
# CONFIG
# =========================
TAKEOUT_DIR = Path(r"C:\Users\Hurley\Desktop\TakeoutZips")
WORK_DIR = Path(r"C:\Users\Hurley\Desktop\PhotoTransfer")
EXIFTOOL = Path(r"C:\Users\Hurley\Desktop\Tools\exiftool.exe")

IMPORT_READY = WORK_DIR / "import_ready"
META_DIR = WORK_DIR / "_meta"

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif"}

IMPORT_READY.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Helpers
# =========================

def run_exiftool(args):
    return subprocess.run(
        args,
        capture_output=True,
        text=True
    )


def epoch_to_exif(epoch):
    dt = datetime.datetime.utcfromtimestamp(int(epoch))
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def apply_timestamp(target_path, ts_epoch, folder):
    """
    Apply timestamp from JSON or fallback to folder year.
    """

    ext = target_path.suffix.lower()

    # -------------------------
    # Try JSON timestamp
    # -------------------------
    if ts_epoch:
        ts_exif = epoch_to_exif(ts_epoch)

        base = [str(EXIFTOOL), "-m", "-overwrite_original"]

        if ext in (".jpg", ".jpeg", ".heic"):
            base += ["-EXIF:all="]
            tags = [
                f"-EXIF:DateTimeOriginal={ts_exif}",
                f"-EXIF:CreateDate={ts_exif}",
                f"-IFD0:ModifyDate={ts_exif}",
            ]

        elif ext == ".png":
            tags = [
                f"-PNG:CreationTime={ts_exif}",
                f"-XMP:CreateDate={ts_exif}",
                f"-XMP:ModifyDate={ts_exif}",
            ]

        elif ext in (".mp4", ".mov"):
            tags = [
                f"-QuickTime:CreateDate={ts_exif}",
                f"-QuickTime:ModifyDate={ts_exif}",
            ]

        else:
            tags = [f"-AllDates={ts_exif}"]

        res = run_exiftool(base + tags + [str(target_path)])

        if res.returncode == 0:
            # filesystem timestamps
            fs_ts = ts_exif.replace(":", "-", 2)
            run_exiftool([
                str(EXIFTOOL),
                "-m",
                f"-FileModifyDate={fs_ts}",
                f"-FileCreateDate={fs_ts}",
                "-overwrite_original",
                str(target_path)
            ])
            return

    # -------------------------
    # Folder-year fallback
    # -------------------------
    parts = folder.name.split()
    year = parts[-1] if parts and parts[-1].isdigit() and len(parts[-1]) == 4 else None

    if year:
        fallback = f"{year}:01:01 12:00:00"
        fs_fallback = fallback.replace(":", "-", 2)

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
            tags = [f"-AllDates={fallback}"]

        run_exiftool(base + tags + [str(target_path)])

        run_exiftool([
            str(EXIFTOOL),
            "-m",
            f"-FileModifyDate={fs_fallback}",
            f"-FileCreateDate={fs_fallback}",
            "-overwrite_original",
            str(target_path)
        ])


def find_matching_media(stem, folder):
    for ext in MEDIA_EXTENSIONS:
        candidate = folder / f"{stem}{ext}"
        if candidate.exists():
            return candidate

    for item in folder.iterdir():
        if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS:
            if item.stem.startswith(stem):
                return item
    return None

# =========================
# MAIN
# =========================

print("📦 Extracting Takeout ZIPs...")

for zip_path in TAKEOUT_DIR.glob("*.zip"):
    extract_target = META_DIR / zip_path.stem
    extract_target.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_target)

json_files = list(META_DIR.rglob("*.json"))
print(f"🔍 Found {len(json_files)} metadata files")

for idx, json_file in enumerate(json_files, start=1):
    print(f"[{idx}/{len(json_files)}] {json_file.name}")

    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
    except Exception:
        continue

    title = data.get("title")
    if not isinstance(title, str):
        continue

    media_stem = Path(title).stem
    folder = json_file.parent
    media_file = find_matching_media(media_stem, folder)

    if not media_file:
        continue

    # HEIC → JPG
    if media_file.suffix.lower() == ".heic":
        target_path = IMPORT_READY / f"{media_stem}.jpg"
        try:
            img = Image.open(media_file)
            img.save(target_path, "JPEG", quality=95)
        except Exception:
            continue
    else:
        target_path = IMPORT_READY / media_file.name
        shutil.copy2(media_file, target_path)

    ts = None
    if "photoTakenTime" in data:
        ts = data["photoTakenTime"].get("timestamp")
    elif "creationTime" in data:
        ts = data["creationTime"].get("timestamp")

    apply_timestamp(target_path, ts, folder)

print("🎉 process_photos complete.")
