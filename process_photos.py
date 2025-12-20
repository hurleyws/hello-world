import json
import zipfile
import shutil
import subprocess
import datetime
import re
from pathlib import Path
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

# =========================
# CONFIG
# =========================
TAKEOUT_DIR = Path(r"E:")
WORK_DIR = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer")
EXIFTOOL = Path(r"C:\Users\hurle\google_icloud\exiftool-13.43_64\exiftool.exe")

IMPORT_READY = WORK_DIR / "import_ready"
META_DIR = WORK_DIR / "_meta"
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif"}

IMPORT_READY.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Helpers
# =========================

def parse_ranges(range_str):
    nums = set()
    for part in range_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                nums.update(range(start, end + 1))
            except: continue
        elif part.isdigit():
            nums.add(int(part))
    return nums

def get_zip_number(filename):
    match = re.search(r'-(\d+)\.zip$', filename.lower())
    return int(match.group(1)) if match else None

def run_exiftool(args):
    return subprocess.run(args, capture_output=True, text=True)

def epoch_to_exif(epoch):
    dt = datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc)
    return dt.strftime("%Y:%m:%d %H:%M:%S")

def find_matching_media(title, folder):
    """
    Advanced matching to find media despite Google's name changes.
    """
    p_title = Path(title)
    stem = p_title.stem
    ext = p_title.suffix.lower()

    # 1. Try Exact Match (Title + Original Extension)
    exact = folder / title
    if exact.exists() and exact.is_file():
        return exact

    # 2. Try Exact Stem + Any Valid Media Extension
    for m_ext in MEDIA_EXTENSIONS:
        candidate = folder / f"{stem}{m_ext}"
        if candidate.exists(): return candidate

    # 3. Try common Google Suffixes (Edited, Duplicates)
    # This covers IMG_1234-edited.jpg or IMG_1234(1).jpg
    suffixes = ["-edited", "(1)", "(2)", "-optimized"]
    for sfx in suffixes:
        for m_ext in MEDIA_EXTENSIONS:
            candidate = folder / f"{stem}{sfx}{m_ext}"
            if candidate.exists(): return candidate

    # 4. Fuzzy Match: Fallback for truncated names
    # Checks if any file in the folder STARTS with the stem from the JSON
    for item in folder.iterdir():
        if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS:
            if item.name.startswith(stem[:10]): # Check first 10 chars for long Apple names
                return item
                
    return None

def apply_timestamp(target_path, ts_epoch, folder):
    ext = target_path.suffix.lower()
    if not ts_epoch:
        return # Skip if no timestamp found
        
    ts_exif = epoch_to_exif(ts_epoch)
    base = [str(EXIFTOOL), "-m", "-overwrite_original"]

    if ext in (".jpg", ".jpeg", ".heic"):
        base += ["-EXIF:all="]
        tags = [f"-EXIF:DateTimeOriginal={ts_exif}", f"-EXIF:CreateDate={ts_exif}", f"-IFD0:ModifyDate={ts_exif}"]
    elif ext == ".png":
        tags = [f"-PNG:CreationTime={ts_exif}", f"-XMP:CreateDate={ts_exif}", f"-XMP:ModifyDate={ts_exif}"]
    elif ext in (".mp4", ".mov"):
        tags = [f"-QuickTime:CreateDate={ts_exif}", f"-QuickTime:ModifyDate={ts_exif}"]
    else:
        tags = [f"-AllDates={ts_exif}"]
    
    run_exiftool(base + tags + [str(target_path)])
    fs_ts = ts_exif.replace(":", "-", 2)
    run_exiftool([str(EXIFTOOL), "-m", f"-FileModifyDate={fs_ts}", f"-FileCreateDate={fs_ts}", "-overwrite_original", str(target_path)])

# =========================
# MAIN
# =========================

all_zips = sorted(list(TAKEOUT_DIR.glob("*.zip")))
print(f"Files found in {TAKEOUT_DIR}")
user_input = input("Enter ZIP numbers to process (e.g., '1', '1-5'): ")
target_indices = parse_ranges(user_input)

zips_to_process = [zp for zp in all_zips if get_zip_number(zp.name) in target_indices]

if not zips_to_process:
    print("No matching ZIPs. Exiting.")
    exit()

print(f"📦 Extracting {len(zips_to_process)} ZIPs...")
for zip_path in zips_to_process:
    extract_target = META_DIR / zip_path.stem
    if not extract_target.exists():
        extract_target.mkdir(parents=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_target)

json_files = list(META_DIR.rglob("*.json"))
print(f"🔍 Processing {len(json_files)} metadata files...")

for idx, json_file in enumerate(json_files, start=1):
    if idx % 25 == 0: print(f"Progress: {idx}/{len(json_files)}...")

    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
    except: continue

# ... inside the loop ...
    title = data.get("title")
    if not title: continue

    # NEW: If title is a list, take the first element
    if isinstance(title, list):
        title = title[0]
    
    # NEW: Safety check to make sure title is actually a string now
    if not isinstance(title, str):
        continue

    folder = json_file.parent
    media_file = find_matching_media(title, folder)
    # ... rest of the code ...

    if not media_file:
        continue # Still can't find it, skip.

    # Destination Logic
    if media_file.suffix.lower() == ".heic":
        # Convert HEIC to JPG for compatibility if desired
        target_path = IMPORT_READY / f"{Path(media_file.name).stem}.jpg"
        if not target_path.exists():
            try:
                img = Image.open(media_file)
                img.save(target_path, "JPEG", quality=95)
            except: continue
    else:
        target_path = IMPORT_READY / media_file.name
        if not target_path.exists():
            shutil.copy2(media_file, target_path)

    # Apply Metadata
    ts = data.get("photoTakenTime", {}).get("timestamp") or data.get("creationTime", {}).get("timestamp")
    apply_timestamp(target_path, ts, folder)

print(f"🎉 Complete. Folder: {IMPORT_READY}")