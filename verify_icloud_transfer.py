from pathlib import Path

# =========================
# CONFIG
# =========================
IMPORT_READY = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\import_ready")
ICLOUD_PHOTOS = Path(r"C:\Users\hurle\Pictures\iCloud Photos\Photos")

def run_audit():
    print(f"--- Migration Audit ---")
    print(f"Checking: {IMPORT_READY}")
    print(f"Against:  {ICLOUD_PHOTOS}\n")

    if not IMPORT_READY.exists():
        print("❌ Error: import_ready folder not found.")
        return
    if not ICLOUD_PHOTOS.exists():
        print("❌ Error: iCloud Photos folder not found.")
        return

    # 1. Get all filenames in Import Ready (lowercase for comparison)
    source_files = {f.name for f in IMPORT_READY.iterdir() if f.is_file()}
    
    # 2. Get all filenames in iCloud (lowercase for comparison)
    # We use a set for speed
    destination_files = {f.name for f in ICLOUD_PHOTOS.iterdir() if f.is_file()}

    # 3. Find the difference
    missing = []
    for filename in source_files:
        if filename not in destination_files:
            missing.append(filename)

    # 4. Report Results
    print(f"📊 Total files in Import Ready: {len(source_files)}")
    print(f"📊 Total files in iCloud folder: {len(destination_files)}")
    print("-" * 30)

    if not missing:
        print("✅ SUCCESS: Every file in import_ready is accounted for in iCloud Photos.")
    else:
        print(f"🚫 MISSING: {len(missing)} files are in Import Ready but NOT in iCloud:")
        print("-" * 30)
        # Sort them so they are easier to look through
        for i, filename in enumerate(sorted(missing), 1):
            print(f"{i}. {filename}")
            
        print("-" * 30)
        print("💡 Troubleshoot Tip: Check if these files are currently 'locked' by another app")
        print("   or if they have weird characters in the filename.")

if __name__ == "__main__":
    run_audit()