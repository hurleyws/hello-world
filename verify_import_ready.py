import zipfile
from pathlib import Path
from collections import defaultdict

# =========================
# CONFIG
# =========================
ZIP_PATH = Path(r"E:\takeout-20251213T162303Z-3-001.zip")
IMPORT_READY = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\import_ready")

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif"}

def is_media_file(name: str) -> bool:
    return Path(name).suffix.lower() in MEDIA_EXTS

def is_duplicate_variant(name: str) -> bool:
    """Skips the Google '(1)' duplicates."""
    return "(1)" in name

# =========================
# RECONCILIATION LOGIC
# =========================

def main():
    print(f"\n--- Comparing ZIP to Import Folder ---")
    print(f"📦 ZIP: {ZIP_PATH.name}")
    print(f"📂 Folder: {IMPORT_READY}\n")

    if not ZIP_PATH.exists():
        print(f"❌ Error: ZIP file not found at {ZIP_PATH}")
        return

    # 1. Scan ZIP
    zip_stems = defaultdict(list)
    zip_count = 0
    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        for name in z.namelist():
            # Convert string name to a Path object to use .name and .stem
            path_in_zip = Path(name)
            base_name = path_in_zip.name
            
            if is_media_file(base_name) and not is_duplicate_variant(base_name):
                # Now .stem will work because path_in_zip is a Path object
                zip_stems[path_in_zip.stem.lower()].append(base_name)
                zip_count += 1

    # 2. Scan Import Ready Folder
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

    # 3. Compare Stems
    z_set = set(zip_stems.keys())
    f_set = set(folder_stems.keys())

    missing_from_folder = sorted(z_set - f_set)
    
    # 4. REPORT
    print(f"📊 Media Items in ZIP: {zip_count}")
    print(f"📊 Media Items in Folder: {folder_count}")
    print("-" * 30)

    if not missing_from_folder:
        print("✅ SUCCESS: Every unique media item in the ZIP exists in the folder.")
    else:
        print(f"🚫 MISSING: {len(missing_from_folder)} items are in the ZIP but NOT the folder:")
        for stem in missing_from_folder[:20]:
            # Pull the first filename associated with this stem from our zip dictionary
            print(f"   - {zip_stems[stem][0]}")
        if len(missing_from_folder) > 20:
            print(f"   ... and {len(missing_from_folder) - 20} more.")

    # 5. Extension Check
    overlap = z_set & f_set
    mismatched_exts = []
    for stem in overlap:
        z_ext = Path(zip_stems[stem][0]).suffix.lower()
        f_ext = Path(folder_stems[stem][0]).suffix.lower()
        if z_ext != f_ext:
            mismatched_exts.append(f"{stem} ({z_ext} -> {f_ext})")

    if mismatched_exts:
        print(f"\n🔄 EXTENSION CHANGES: {len(mismatched_exts)} items (likely HEIC to JPG conversion)")
        for item in mismatched_exts[:5]:
            print(f"   - {item}")

if __name__ == "__main__":
    main()