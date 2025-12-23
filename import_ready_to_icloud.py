import shutil
import os
import stat
from pathlib import Path

# =========================
# CONFIG
# =========================
IMPORT_READY = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\import_ready")
ICLOUD_PHOTOS = Path(r"C:\Users\hurle\Pictures\iCloud Photos\Photos")
META_DIR = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\_meta")
LOG_FILE = Path(r"C:\Users\hurle\google_icloud\migration_progress.txt")

# =========================
# HELPER: Force Delete
# =========================
def remove_readonly(func, path, exc_info):
    """
    Error handler for shutil.rmtree to delete read-only files on Windows.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)

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
        # Optional: Ask if they want to clean up anyway?
        if input("Clean up empty folders? (y/n): ").lower() == 'y':
            shutil.rmtree(META_DIR, onerror=remove_readonly)
            print("🧹 _meta cleared.")
        return

    print(f"🚀 Moving {total_to_move} files to iCloud Photos...")

    # Ensure destination exists
    ICLOUD_PHOTOS.mkdir(parents=True, exist_ok=True)

    # 3. Move and Overwrite
    for f in files_to_move:
        dest_path = ICLOUD_PHOTOS / f.name
        
        # Delete existing file in destination to ensure clean overwrite
        if dest_path.exists():
            try:
                dest_path.unlink()
            except PermissionError:
                print(f"⚠️ specific file locked, skipping overwrite: {f.name}")
                continue
            
        shutil.move(str(f), str(dest_path))

    # 4. Verification Check
    print("\n🔍 Verifying transfer...")
    
    missing_count = 0
    for f in files_to_move:
        if not (ICLOUD_PHOTOS / f.name).exists():
            print(f"  ❌ Missing: {f.name}")
            missing_count += 1

    # 5. Logging & Cleanup
    if missing_count == 0:
        print(f"✅ Success! All {total_to_move} files verified in iCloud folder.")
        
        # Log the success
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            log.write(f"ZIP: {zip_num} | Files: {total_to_move} | Status: Verified & Complete\n")
        print(f"📝 Progress logged to {LOG_FILE}")
        
        # --- CLEANUP ACTION ---
        print("🧹 Cleaning up workspace...")
        
        # 1. Clear import_ready (it should be empty, but just in case)
        # We don't delete the folder itself, just any leftover junk
        for item in IMPORT_READY.iterdir():
            if item.is_dir():
                shutil.rmtree(item, onerror=remove_readonly)
            else:
                item.unlink()
                
        # 2. NUKE the _meta folder
        if META_DIR.exists():
            print(f"   Deleting {META_DIR}...")
            shutil.rmtree(META_DIR, onerror=remove_readonly)
            # Recreate the empty folder so the next script doesn't crash
            META_DIR.mkdir()
            print("   _meta folder wiped and reset.")
            
        print("\n✨ Batch Complete! You are ready for the next ZIP.")

    else:
        print(f"⚠️ Warning: {missing_count} files could not be verified in the destination.")
        print("🛑 Cleanup ABORTED to preserve files for troubleshooting.")

if __name__ == "__main__":
    migrate_to_icloud()