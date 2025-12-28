import zipfile
import random
import re
import datetime
from pathlib import Path

# =========================
# CONFIG
# =========================
TAKEOUT_DIR = Path(r"E:") 
ICLOUD_PHOTOS = Path(r"C:\Users\hurle\Pictures\iCloud Photos\Photos")
LOG_FILE = Path(r"C:\Users\hurle\google_icloud\migration_progress.txt")

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif", ".avi", ".3gp", ".m4v", ".mpg", ".flv", ".wmv"}
SAMPLE_SIZE = 50  # How many files to test per ZIP

# =========================
# HELPERS
# =========================
def get_zip_path(zip_num):
    """Finds the specific ZIP file based on user number input."""
    for z in TAKEOUT_DIR.glob("*.zip"):
        match = re.search(r'-(\d+)\.zip$', z.name)
        if match and int(match.group(1)) == int(zip_num):
            return z
    return None

def get_expected_filename(zip_filename):
    """
    Predicts what the file *should* be named in iCloud based on our migration logic.
    """
    p = Path(zip_filename)
    stem = p.stem
    ext = p.suffix.lower()

    # Logic from migration script:
    if ext == ".heic":
        return f"{stem}.jpg"
    if ext == ".png":
        return f"{stem}.jpg"
    if ext in {".mov", ".avi", ".3gp", ".m4v", ".flv", ".wmv", ".mpg"}:
        return f"{stem}.mp4"
    
    # Default: extension stays same (jpg, mp4, gif)
    return p.name

def log_qa_result(zip_name, total_samples, passed, failed, missing_list):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "PASSED" if failed == 0 else "WARNING - MISSING FILES"
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"🕵️ QA CHECK: {now} | ZIP: {zip_name} | RESULT: {status}\n")
        f.write(f"{'='*60}\n")
        f.write(f"   • Samples Checked: {total_samples}\n")
        f.write(f"   • Found in iCloud: {passed}\n")
        f.write(f"   • Missing: {failed}\n")
        
        if missing_list:
            f.write("\n   [MISSING FILES DETAILS]\n")
            for item in missing_list:
                f.write(f"   ❌ ZIP: {item['original']}  -->  EXPECTED: {item['expected']}\n")
        
        f.write(f"{'='*60}\n")
    
    print(f"\n📝 QA Log written to {LOG_FILE}")

# =========================
# MAIN
# =========================
def main():
    print("--- 🕵️ RANDOM SAMPLING QA TOOL ---")
    
    user_input = input("Enter ZIP number to audit (e.g. 1): ")
    zip_path = get_zip_path(user_input)

    if not zip_path:
        print(f"❌ Could not find ZIP #{user_input} in {TAKEOUT_DIR}")
        return

    print(f"📦 Scanning {zip_path.name}...")
    
    # 1. Gather Population
    media_files = []
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            # Skip directories, JSONs, and duplicate (1) files
            if not name.endswith('/') and Path(name).suffix.lower() in MEDIA_EXTS:
                if "(1)" not in name and "(2)" not in name:
                    media_files.append(name)

    total_files = len(media_files)
    if total_files == 0:
        print("⚠️ No media files found in this ZIP to sample.")
        return

    # 2. Pick Random Sample
    actual_sample_size = min(total_files, SAMPLE_SIZE)
    samples = random.sample(media_files, actual_sample_size)
    
    print(f"🎲 Randomly selected {actual_sample_size} files out of {total_files}...")
    print(f"🔍 Verifying existence in iCloud folder...")

    # 3. verify
    passed = 0
    failed = 0
    missing_details = []

    for original in samples:
        # We only care about the filename, not the folder path inside the zip
        original_flat_name = Path(original).name
        
        # Calculate what it should look like in iCloud
        expected_name = get_expected_filename(original_flat_name)
        
        # Check iCloud
        target_path = ICLOUD_PHOTOS / expected_name
        
        if target_path.exists():
            passed += 1
            # Optional: Print success dots
            print(".", end="", flush=True)
        else:
            failed += 1
            print("X", end="", flush=True)
            missing_details.append({
                "original": original_flat_name, 
                "expected": expected_name
            })

    print(f"\n\n📊 RESULTS for {zip_path.name}")
    print(f"   ✅ Found: {passed}")
    print(f"   ❌ Missing: {failed}")

    if missing_details:
        print("\n⚠️ The following sampled files were NOT found:")
        for m in missing_details:
            print(f"   - Zip says: {m['original']} -> Looked for: {m['expected']}")
    else:
        print("\n✨ PERFECT SAMPLE! All checked files are present and converted correctly.")

    # 4. Log
    log_qa_result(zip_path.name, actual_sample_size, passed, failed, missing_details)

if __name__ == "__main__":
    main()