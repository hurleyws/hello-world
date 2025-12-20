import shutil
import os
from pathlib import Path

# =========================
# CONFIG
# =========================
IMPORT_READY = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\import_ready")
ICLOUD_PHOTOS = Path(r"C:\Users\hurle\Pictures\iCloud Photos\Photos")
LOG_FILE = Path(r"C:\Users\hurle\google_icloud\migration_progress.txt")

# =========================
# MAIN
# =========================

def migrate_to_icloud():
    # 1. Get user context
    zip_num = input("Which ZIP number(s) are you completing? (e.g., 001): ")
    
    if not IMPORT_READY.exists():
        print("❌ Error: import_ready folder not found.")
        return

    # 2. Get list of files to move
    files_to_move = [f for f in IMPORT_READY.iterdir() if f.is_file()]
    total_to_move = len(files_to_move)

    if total_to_move == 0:
        print("⚠️ No files found in import_ready to move.")
        return

    print(f"🚀 Moving {total_to_move} files to iCloud Photos...")

    # Ensure destination exists
    ICLOUD_PHOTOS.mkdir(parents=True, exist_ok=True)

    # 3. Move and Overwrite
    for f in files_to_move:
        dest_path = ICLOUD_PHOTOS / f.name
        
        # shutil.move doesn't have an 'overwrite' flag like copy, 
        # so we delete the destination first if it exists.
        if dest_path.exists():
            dest_path.unlink() 
            
        shutil.move(str(f), str(dest_path))

    # 4. Verification Check
    print("\n🔍 Verifying transfer...")
    
    # We check if the files we just moved now exist in the iCloud folder
    # Note: We check by filename
    missing_count = 0
    for f in files_to_move:
        if not (ICLOUD_PHOTOS / f.name).exists():
            print(f"  ❌ Missing: {f.name}")
            missing_count += 1

    # 5. Logging
    if missing_count == 0:
        print(f"✅ Success! All {total_to_move} files verified in iCloud folder.")
        
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            timestamp = shutil.os.path.getmtime(ICLOUD_PHOTOS) # Placeholder for now
            log.write(f"ZIP: {zip_num} | Files: {total_to_move} | Status: Verified & Complete\n")
        
        print(f"📝 Progress logged to {LOG_FILE}")
        
        # Cleanup import_ready (it should be empty now anyway due to shutil.move)
        print("🧹 Cleaning up import_ready...")
    else:
        print(f"⚠️ Warning: {missing_count} files could not be verified in the destination.")

if __name__ == "__main__":
    migrate_to_icloud()