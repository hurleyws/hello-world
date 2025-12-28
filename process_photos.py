import json
import zipfile
import shutil
import subprocess
import datetime
import re
import os
import stat
import sys
import random
from pathlib import Path
from PIL import Image
from collections import defaultdict
import pillow_heif

pillow_heif.register_heif_opener()

# =========================
# CONFIGURATION
# =========================
TAKEOUT_DIR = Path(r"D:") 
WORK_DIR = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer")
ICLOUD_PHOTOS = Path(r"C:\Users\hurle\Pictures\iCloud Photos\Photos")
LOG_FILE = Path(r"C:\Users\hurle\google_icloud\migration_progress.txt")

# Tools
EXIFTOOL = Path(r"C:\Users\hurle\google_icloud\exiftool-13.43_64\exiftool.exe")
# Note: ffprobe is usually in the same bin folder as ffmpeg
FFMPEG_EXE = Path(r"C:\Users\hurle\google_icloud\ffmpeg-2025-12-22-git-c50e5c7778-essentials_build\bin\ffmpeg.exe")
FFPROBE_EXE = Path(r"C:\Users\hurle\google_icloud\ffmpeg-2025-12-22-git-c50e5c7778-essentials_build\bin\ffprobe.exe")

# Internal Paths
IMPORT_READY = WORK_DIR / "import_ready"
META_DIR = WORK_DIR / "_meta"
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif", ".avi", ".3gp", ".m4v", ".mpg", ".flv", ".wmv"}
QA_SAMPLE_SIZE = 50

# Setup
IMPORT_READY.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# GLOBAL STATS
# =========================
STATS = {
    "zip_files_count": defaultdict(int),
    "zip_folders": set(),
    "processed_count": defaultdict(int),
    "videos_fixed_transcode": 0,
    "videos_fixed_remux": 0,
    "png_converted": 0,
    "heic_converted": 0,
    "orphans_rescued": 0,
    "dates_json": 0,
    "dates_internal": 0,
    "dates_inferred": 0,
    "dates_fallback": 0,
}

# =========================
# HELPER FUNCTIONS
# =========================
def remove_readonly(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def write_log(zip_input, status, details_list):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"📅 DATE: {now} | BATCH: {zip_input} | STATUS: {status}\n")
        f.write(f"{'='*60}\n")
        
        f.write("\n[📂 1. ZIP CONTENTS]\n")
        f.write(f"   • Folders: {', '.join(list(STATS['zip_folders'])[:5])}...\n")
        for ext, count in sorted(STATS['zip_files_count'].items()):
            f.write(f"   • {ext}: {count}\n")
            
        f.write("\n[⚙️ 2. PROCESSING METRICS]\n")
        f.write(f"   • Orphans Rescued: {STATS['orphans_rescued']}\n")
        f.write(f"   • Videos Re-Encoded (Safe Mode): {STATS['videos_fixed_transcode']}\n")
        f.write(f"   • Videos Remuxed (Fast Mode): {STATS['videos_fixed_remux']}\n")
        f.write(f"   • HEIC->JPG: {STATS['heic_converted']}\n")
        f.write(f"   • PNG->JPG: {STATS['png_converted']}\n")
        f.write(f"   • Dates from JSON: {STATS['dates_json']}\n")
        f.write(f"   • Dates Inferred: {STATS['dates_inferred']}\n")
        
        f.write("\n[📦 3. IMPORT READY CONTENT]\n")
        f.write(f"   • Total Files: {sum(STATS['processed_count'].values())}\n")
        for ext, count in sorted(STATS['processed_count'].items()):
            f.write(f"   • {ext}: {count}\n")
            
        f.write("\n[🔍 4. AUDIT & ERRORS]\n")
        for line in details_list:
            f.write(f"   {line}\n")
        f.write(f"{'='*60}\n")
    print(f"\n📝 Log updated: {LOG_FILE}")

def run_exiftool(args):
    return subprocess.run(args, capture_output=True, text=True)

def epoch_to_exif(epoch):
    dt = datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc)
    return dt.strftime("%Y:%m:%d %H:%M:%S")

def get_internal_date(file_path):
    cmd = [str(EXIFTOOL), "-DateTimeOriginal", "-s3", str(file_path)]
    res = run_exiftool(cmd)
    if res.returncode == 0 and res.stdout.strip(): return res.stdout.strip()
    cmd = [str(EXIFTOOL), "-CreateDate", "-s3", str(file_path)]
    res = run_exiftool(cmd)
    if res.returncode == 0 and res.stdout.strip(): return res.stdout.strip()
    return None

def get_year_from_folder(file_path):
    match = re.search(r"(?:19|20)\d{2}", file_path.parent.name)
    if match: return f"{match.group(0)}:01:01 12:00:00"
    return None

# =========================
# CORE PROCESSING LOGIC
# =========================

def check_needs_transcode(input_path):
    """
    X-Ray: Uses FFprobe to see if the video is HEVC/H.265.
    Returns True if it needs Transcoding (Safe Mode).
    Returns False if it is safe to Copy (Fast Mode).
    """
    if not FFPROBE_EXE.exists(): return True # Safety fallback
    
    cmd = [
        str(FFPROBE_EXE), "-v", "error", 
        "-select_streams", "v:0", 
        "-show_entries", "stream=codec_name", 
        "-of", "default=noprint_wrappers=1:nokey=1", 
        str(input_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    codec = res.stdout.strip().lower()
    
    # If it is HEVC (hvc1/hev1) or ancient MJPEG, we force transcode.
    # If it is h264, we can safely copy.
    if "h264" in codec or "avc1" in codec:
        return False
    return True

def fix_video(input_path):
    output_path = input_path.with_suffix(".mp4")
    if output_path == input_path: 
        output_path = input_path.with_stem(input_path.stem + "_fixed")
    
    # FEEDBACK 1: Let the user know we are checking the file
    print(f"  🔍 Checking video codec: {input_path.name}...", end="", flush=True)
    
    needs_transcode = check_needs_transcode(input_path)
    
    if needs_transcode:
        # FEEDBACK 2: The "Slow" Path
        print("\n     ⚠️ HEVC detected. Transcoding to H.264 (This may take time)...")
        
        cmd = [
            str(FFMPEG_EXE), "-y", "-i", str(input_path), 
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", 
            str(output_path)
        ]
        stat_key = "videos_fixed_transcode"
    else:
        # FEEDBACK 3: The "Fast" Path
        print(" OK (H.264). Remuxing container.")
        
        cmd = [
            str(FFMPEG_EXE), "-y", "-i", str(input_path), 
            "-c", "copy", "-movflags", "+faststart", "-f", "mp4", 
            str(output_path)
        ]
        stat_key = "videos_fixed_remux"

    # Run FFmpeg
    res = subprocess.run(cmd, capture_output=True)
    
    if res.returncode == 0:
        STATS[stat_key] += 1
        try:
            input_path.unlink()
            if output_path.name != input_path.with_suffix(".mp4").name: 
                output_path.rename(input_path.with_suffix(".mp4"))
            return input_path.with_suffix(".mp4")
        except OSError: return output_path
    
    # If failed
    print(f"     ❌ FFmpeg Error on {input_path.name}")
    return input_path

def fix_png(input_path):
    try:
        output_path = input_path.with_suffix(".jpg")
        with Image.open(input_path) as img:
            img.convert('RGB').save(output_path, quality=95)
        input_path.unlink()
        STATS["png_converted"] += 1
        return output_path
    except: return input_path

def process_media_compatibility(file_path):
    ext = file_path.suffix.lower()
    if ext == ".png": return fix_png(file_path)
    if ext in {".mov", ".avi", ".3gp", ".m4v", ".flv", ".wmv", ".mpg"}: return fix_video(file_path)
    return file_path

def apply_timestamp(target_path, ts_epoch, source_path):
    ts = None
    if ts_epoch: 
        ts = epoch_to_exif(ts_epoch)
        STATS["dates_json"] += 1
    if not ts: 
        ts = get_internal_date(source_path)
        if ts: STATS["dates_internal"] += 1
    if not ts:
        ts = get_year_from_folder(source_path)
        if ts: STATS["dates_inferred"] += 1
    if not ts:
        ts = datetime.datetime.fromtimestamp(source_path.stat().st_mtime).strftime("%Y:%m:%d %H:%M:%S")
        STATS["dates_fallback"] += 1

    base = [str(EXIFTOOL), "-m", "-overwrite_original"]
    tags = [f"-AllDates={ts}"]
    ext = target_path.suffix.lower()
    if ext in (".jpg", ".jpeg", ".heic"):
        base += ["-EXIF:all="]
        tags = [f"-EXIF:DateTimeOriginal={ts}", f"-EXIF:CreateDate={ts}", f"-IFD0:ModifyDate={ts}"]
    elif ext == ".png":
        tags = [f"-PNG:CreationTime={ts}", f"-XMP:CreateDate={ts}"]
    elif ext in (".mp4", ".mov"):
        tags = [f"-QuickTime:CreateDate={ts}", f"-QuickTime:ModifyDate={ts}"]

    run_exiftool(base + tags + [str(target_path)])
    fs_ts = ts.replace(":", "-", 2)
    run_exiftool([str(EXIFTOOL), "-m", f"-FileModifyDate={fs_ts}", f"-FileCreateDate={fs_ts}", "-overwrite_original", str(target_path)])

def find_matching_media(title, folder):
    p_title = Path(title)
    stem = p_title.stem
    exact = folder / title
    if exact.exists(): return exact
    for ext in MEDIA_EXTENSIONS:
        if (folder / f"{stem}{ext}").exists(): return folder / f"{stem}{ext}"
    for sfx in ["-edited", "(1)", "(2)"]:
        for ext in MEDIA_EXTENSIONS:
            if (folder / f"{stem}{sfx}{ext}").exists(): return folder / f"{stem}{sfx}{ext}"
    for item in folder.iterdir():
        if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS and item.name.startswith(stem[:10]): return item
    return None

# =========================
# QA SAMPLING LOGIC
# =========================
def get_expected_filename(zip_filename):
    p = Path(zip_filename)
    stem = p.stem
    ext = p.suffix.lower()
    if ext == ".heic": return f"{stem}.jpg"
    if ext == ".png": return f"{stem}.jpg"
    if ext in {".mov", ".avi", ".3gp", ".m4v", ".flv", ".wmv", ".mpg"}: return f"{stem}.mp4"
    return p.name

def run_qa_sampling(zip_path):
    print(f"\n🎲 Running QA Spot Check on: {zip_path.name}...")
    media_files = []
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            if not name.endswith('/') and Path(name).suffix.lower() in MEDIA_EXTENSIONS:
                if "(1)" not in name: media_files.append(name)

    if not media_files:
        print("   ⚠️ No media to sample.")
        return

    sample_size = min(len(media_files), QA_SAMPLE_SIZE)
    samples = random.sample(media_files, sample_size)
    
    passed, failed, missing_list = 0, 0, []
    
    for original in samples:
        expected = get_expected_filename(Path(original).name)
        if (ICLOUD_PHOTOS / expected).exists(): passed += 1
        else:
            failed += 1
            missing_list.append(f"{Path(original).name} -> {expected}")

    # LOG QA RESULT
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"🕵️ QA CHECK: {zip_path.name} | SAMPLES: {sample_size}\n")
        f.write(f"   ✅ FOUND: {passed} | ❌ MISSING: {failed}\n")
        if missing_list:
            for m in missing_list: f.write(f"   ⚠️ Missing: {m}\n")
        f.write(f"{'='*60}\n")
    
    if failed == 0: print(f"   ✅ QA PASSED ({passed}/{sample_size} confirmed in iCloud)")
    else: print(f"   ❌ QA WARNING ({failed} missing files! Check logs.)")

# =========================
# MAIN EXECUTION
# =========================
def main():
    print("--- GOOGLE TAKEOUT MASTER ENGINE ---")
    
    # 1. SCAN
    all_zips = sorted(list(TAKEOUT_DIR.glob("*.zip")))
    user_input = input("Enter ZIP numbers to process (e.g., '1', '1-5'): ")
    
    target_indices = set()
    for part in user_input.split(','):
        part = part.strip()
        if '-' in part:
            try: s, e = map(int, part.split('-')); target_indices.update(range(s, e + 1))
            except: pass
        elif part.isdigit(): target_indices.add(int(part))
        
    zips = [z for z in all_zips if (m := re.search(r'-(\d+)\.zip$', z.name)) and int(m.group(1)) in target_indices]

    if not zips:
        print("❌ No valid ZIPs found.")
        return

    # 2. EXTRACT
    print(f"\n📦 Extracting {len(zips)} ZIPs...")
    for z in zips:
        dest = META_DIR / z.stem
        if not dest.exists():
            dest.mkdir(parents=True)
            with zipfile.ZipFile(z, "r") as zf: zf.extractall(dest)
        
        # Stats
        for item in dest.rglob("*"):
            if item.is_dir(): STATS["zip_folders"].add(item.name)
            elif item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS:
                STATS["zip_files_count"][item.suffix.lower()] += 1

    # 3. PROCESS
    processed = set()
    json_files = []
    for z in zips: json_files.extend(list((META_DIR / z.stem).rglob("*.json")))
    
    print(f"🔍 Phase 1: Processing {len(json_files)} JSONs...")
    for i, jf in enumerate(json_files):
        if i % 50 == 0: print(f"  Progress: {i}/{len(json_files)}...")
        try: data = json.loads(jf.read_text(encoding="utf-8"))
        except: continue
        
        title = data.get("title")
        if isinstance(title, list): title = title[0]
        if not title or not isinstance(title, str): continue
        
        media = find_matching_media(title, jf.parent)
        if not media: continue
        
        processed.add(media)
        
        target = IMPORT_READY / media.name
        if media.suffix.lower() == ".heic":
            target = IMPORT_READY / f"{media.stem}.jpg"
            if not target.exists():
                try: Image.open(media).save(target, "JPEG", quality=95); STATS["heic_converted"]+=1
                except: continue
        elif not target.exists():
            shutil.copy2(media, target)
            target = process_media_compatibility(target)
            
        ts = data.get("photoTakenTime", {}).get("timestamp") or data.get("creationTime", {}).get("timestamp")
        apply_timestamp(target, ts, media)

    # 4. ORPHANS
    print(f"\n🦅 Phase 2: Scavenging Orphans...")
    for z in zips:
        for f in (META_DIR / z.stem).rglob("*"):
            if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS and f not in processed:
                print(f"  Rescuing: {f.name}")
                STATS["orphans_rescued"] += 1
                target = IMPORT_READY / f.name
                if target.exists() or (IMPORT_READY / f.with_suffix(".mp4").name).exists(): continue
                
                if f.suffix.lower() == ".heic":
                    target = IMPORT_READY / f"{f.stem}.jpg"
                    if not target.exists():
                        try: Image.open(f).save(target, "JPEG", quality=95); STATS["heic_converted"]+=1
                        except: continue
                else:
                    shutil.copy2(f, target)
                    target = process_media_compatibility(target)
                apply_timestamp(target, None, f)

    # 5. STATS
    for f in IMPORT_READY.iterdir():
        if f.is_file(): STATS["processed_count"][f.suffix.lower()] += 1

    # 6. VERIFY ZIP vs IMPORT READY
    print("\n🔍 CHECK 1: Verifying ZIP Contents...")
    missing_in_import = []
    import_stems = {f.stem.lower() for f in IMPORT_READY.iterdir()}
    for z in zips:
        with zipfile.ZipFile(z, "r") as zf:
            for name in zf.namelist():
                p = Path(name)
                if p.suffix.lower() in MEDIA_EXTENSIONS and "(1)" not in p.name:
                    if p.stem.lower() not in import_stems:
                        missing_in_import.append(f"{z.name} -> {p.name}")

    if missing_in_import:
        print(f"❌ STOP! {len(missing_in_import)} files missing from Import Ready.")
        write_log(user_input, "FAILED - ZIP MISMATCH", missing_in_import)
        return
    print("✅ Check 1 Passed.")

    # 7. MOVE TO ICLOUD
    print(f"\n🚀 Moving {sum(STATS['processed_count'].values())} files to iCloud...")
    if not ICLOUD_PHOTOS.exists(): ICLOUD_PHOTOS.mkdir(parents=True)
    files_moved = []
    for f in IMPORT_READY.iterdir():
        if f.is_file():
            files_moved.append(f.name)
            dest = ICLOUD_PHOTOS / f.name
            if dest.exists(): 
                try: dest.unlink()
                except: print(f"  ⚠️ Locked: {f.name}"); continue
            shutil.move(str(f), str(dest))

    # 8. AUDIT ICLOUD
    print("\n🔍 CHECK 2: Auditing iCloud Folder...")
    missing_in_icloud = []
    for name in files_moved:
        if not (ICLOUD_PHOTOS / name).exists(): missing_in_icloud.append(name)
    if missing_in_icloud:
        print(f"❌ STOP! {len(missing_in_icloud)} files failed to verify in iCloud.")
        write_log(user_input, "FAILED - ICLOUD TRANSFER ERROR", missing_in_icloud)
        return
    print("✅ Check 2 Passed.")

    # 9. SUCCESS LOG
    write_log(user_input, "SUCCESS", ["All checks passed.", "Cleaned up workspace."])

    # 10. QA SPOT CHECK
    print("\n🎲 Running Final QA Checks...")
    for z in zips:
        run_qa_sampling(z)
        
    # 11. CLEANUP
    print("\n🧹 Cleaning up workspace...")
    shutil.rmtree(META_DIR, onerror=remove_readonly)
    META_DIR.mkdir()
    for f in IMPORT_READY.iterdir(): 
        try: f.unlink() 
        except: pass
        
    print(f"\n✨ BATCH {user_input} COMPLETE!")

if __name__ == "__main__":
    main()