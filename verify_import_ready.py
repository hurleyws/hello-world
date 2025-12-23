import zipfile
import re
from pathlib import Path
from collections import defaultdict

# =========================
# CONFIG
# =========================
# NOTE: Update this to where your ZIPs live (e.g., E:)
TAKEOUT_DIR = Path(r"E:") 
IMPORT_READY = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\import_ready")

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif"}

def is_media_file(name: str) -> bool:
    return Path(name).suffix.lower() in MEDIA_EXTS

def is_duplicate_variant(name: str) -> bool:
    return "(1)" in name

def get_target_zip(zip_num_input):
    """
    Finds the zip file that ends with the user's number.
    e.g. input "2" finds "takeout-....-002.zip"
    """
    try:
        target_num = int(zip_num_input)
    except ValueError:
        return None
        
    # Look for files matching the pattern ending in -{num}.zip
    for zip_file in TAKEOUT_DIR.glob("*.zip"):
        # Extract number from filename like "...-002.zip"
        match = re.search(r'-(\d+)\.zip$', zip_file.name)
        if match and int(match.group(1)) == target_num:
            return zip_file
    return None

# =========================
# MAIN
# =========================

def main():
    print(f"--- Verify Import Ready ---")
    
    # 1. Ask User for ZIP Number
    user_num = input("Enter ZIP number to verify (e.g. 2): ")
    zip_path = get_target_zip(user_num)
    
    if not zip_path:
        print(f"❌ Error: Could not find a ZIP file ending in number {user_num} in {TAKEOUT_DIR}")
        return

    print(f"📦 Checking contents of: {zip_path.name}")
    print(f"📂 Against folder: {IMPORT_READY.name}\n")

    # 2. Scan ZIP
    zip_stems = defaultdict(list)
    zip_count = 0
    with zipfile.ZipFile(zip_path, "r") as z:
        for name in z.namelist():
            path_in_zip = Path(name)
            base_name = path_in_zip.name
            
            if is_media_file(base_name) and not is_duplicate_variant(base_name):
                zip_stems[path_in_zip.stem.lower()].append(base_name)
                zip_count += 1

    # 3. Scan Import Ready Folder
    folder_stems = defaultdict(list)
    folder_count = 0
    if IMPORT_READY.exists():
        for p in IMPORT_READY.iterdir():
            if p.is_file() and is_media_file(p.name):
                folder_stems[p.stem.lower()].append(p.name)
                folder_count += 1
    else:
        print(f"❌ Error: Import folder not found at {IMPORT_READY}")
        return

    # 4. Compare
    z_set = set(zip_stems.keys())
    f_set = set(folder_stems.keys())

    missing_from_folder = sorted(z_set - f_set)
    
    # 5. Report
    print(f"📊 Media Items in {zip_path.name}: {zip_count}")
    print(f"📊 Media Items in Folder: {folder_count}")
    print("-" * 30)

    if not missing_from_folder:
        print("✅ SUCCESS: Every unique media item in the ZIP exists in the folder.")
    else:
        print(f"🚫 MISSING: {len(missing_from_folder)} items are in the ZIP but NOT the folder:")
        for stem in missing_from_folder[:20]:
            print(f"   - {zip_stems[stem][0]}")
        if len(missing_from_folder) > 20:
            print(f"   ... and {len(missing_from_folder) - 20} more.")

    # Extension Check
    overlap = z_set & f_set
    mismatched_exts = []
    for stem in overlap:
        z_ext = Path(zip_stems[stem][0]).suffix.lower()
        f_ext = Path(folder_stems[stem][0]).suffix.lower()
        if z_ext != f_ext:
            mismatched_exts.append(f"{stem} ({z_ext} -> {f_ext})")

    if mismatched_exts:
        print(f"\n🔄 EXTENSION CHANGES: {len(mismatched_exts)} items")

if __name__ == "__main__":
    main()