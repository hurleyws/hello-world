import json
import zipfile
import shutil
import subprocess
import datetime
import re
import os
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
    p_title = Path(title)
    stem = p_title.stem
    
    # 1. Exact
    exact = folder / title
    if exact.exists() and exact.is_file(): return exact

    # 2. Extensions
    for m_ext in MEDIA_EXTENSIONS:
        candidate = folder / f"{stem}{m_ext}"
        if candidate.exists(): return candidate

    # 3. Suffixes
    suffixes = ["-edited", "(1)", "(2)", "-optimized"]
    for sfx in suffixes:
        for m_ext in MEDIA_EXTENSIONS:
            candidate = folder / f"{stem}{sfx}{m_ext}"
            if candidate.exists(): return candidate

    # 4. Fuzzy
    for item in folder.iterdir():
        if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS:
            if item.name.startswith(stem[:10]): 
                return item
    return None

def get_internal_date(file_path):
    """
    Tries to read the existing DateTimeOriginal from the file itself.
    """
    cmd = [str(EXIFTOOL), "-DateTimeOriginal", "-s3", str(file_path)]
    res = run_exiftool(cmd)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    
    # Try CreateDate if DateTimeOriginal failed (common for videos)
    cmd = [str(EXIFTOOL), "-CreateDate", "-s3", str(file_path)]
    res = run_exiftool(cmd)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    return None

def get_year_from_folder(file_path):
    """
    Checks the parent folder name for a 4-digit year (19xx or 20xx).
    Returns "YYYY:01:01 12:00:00" if found.
    """
    parent_name = file_path.parent.name
    # Regex looks for 19xx or 20xx
    match = re.search(r"(?:19|20)\d{2}", parent_name)
    if match:
        year = match.group(0)
        return f"{year}:01:01 12:00:00"
    return None

def apply_timestamp(target_path, ts_epoch, source_file_path):
    """
    Applies timestamp. 
    Priority 1: JSON Timestamp
    Priority 2: Existing Internal Metadata
    Priority 3: Folder Name Year (The "Sherlock" fallback)
    Priority 4: File Modification Time (Last resort)
    """
    ts_exif = None
    
    # PRIORITY 1: JSON
    if ts_epoch:
        ts_exif = epoch_to_exif(ts_epoch)
    
    # PRIORITY 2: Internal Metadata
    if not ts_exif:
        ts_exif = get_internal_date(source_file_path)
            
    # PRIORITY 3: Folder Name Year
    if not ts_exif:
        ts_exif = get_year_from_folder(source_file_path)
        if ts_exif:
            print(f"    📅 Inferred date from folder: {source_file_path.parent.name} -> {ts_exif}")

    # PRIORITY 4: File System Fallback
    if not ts_exif:
        stat = source_file_path.stat()
        dt = datetime.datetime.fromtimestamp(stat.st_mtime)
        ts_exif = dt.strftime("%Y:%m:%d %H:%M:%S")

    # Apply the determined date
    ext = target_path.suffix.lower()
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
    
    # Fix file system dates
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
        print(f"   Unzipping {zip_path.name}...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_target)
    else:
        print(f"   Skipping unzip for {zip_path.name} (already extracted)")

processed_files = set()

# =========================
# PHASE 1: JSON DRIVEN
# =========================
json_files = []
for zp in zips_to_process:
    specific_folder = META_DIR / zp.stem
    if specific_folder.exists():
        files_in_this_zip = list(specific_folder.rglob("*.json"))
        json_files.extend(files_in_this_zip)

print(f"🔍 Phase 1: Processing {len(json_files)} metadata files...")

for idx, json_file in enumerate(json_files, start=1):
    if idx % 50 == 0: print(f"  JSON Progress: {idx}/{len(json_files)}...")

    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
    except: continue

    title = data.get("title")
    if not title: continue
    if isinstance(title, list): title = title[0]
    if not isinstance(title, str): continue

    folder = json_file.parent
    media_file = find_matching_media(title, folder)

    if not media_file: continue 

    processed_files.add(media_file)

    if media_file.suffix.lower() == ".heic":
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

    ts = data.get("photoTakenTime", {}).get("timestamp") or data.get("creationTime", {}).get("timestamp")
    apply_timestamp(target_path, ts, media_file)

# =========================
# PHASE 2: ORPHAN SCAVENGER
# =========================
print(f"\n🦅 Phase 2: Scavenging orphans (Media without JSON in this ZIP)...")

orphan_count = 0
for zp in zips_to_process:
    extract_root = META_DIR / zp.stem
    for f in extract_root.rglob("*"):
        if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS:
            if f not in processed_files:
                orphan_count += 1
                
                # --- NEW PROGRESS INDICATOR ---
                print(f"  🦅 Rescuing orphan: {f.name}")
                
                target_path = IMPORT_READY / f.name
                if target_path.exists(): continue

                if f.suffix.lower() == ".heic":
                    target_path = IMPORT_READY / f"{f.stem}.jpg"
                    if not target_path.exists():
                        try:
                            img = Image.open(f)
                            img.save(target_path, "JPEG", quality=95)
                        except: continue
                else:
                    shutil.copy2(f, target_path)
                
                apply_timestamp(target_path, None, f)

print(f"✅ Scavenged {orphan_count} orphans.")
print(f"🎉 Batch Complete. Folder: {IMPORT_READY}")