import zipfile
from pathlib import Path
from collections import defaultdict

# -------------------------
# CONFIG – EDIT THESE
# -------------------------
ZIP_PATH = r"C:\Users\Hurley\Desktop\TakeoutZips\takeout-20250827T004600Z-1-017.zip"
ICLOUD_DIR = Path(r"C:\Users\Hurley\Pictures\iCloud Photos\Photos")

# Only treat these as real media
MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".gif"}

def is_media_file(name: str) -> bool:
    """Return True if filename is a media file we care about."""
    n = name.lower()
    ext = Path(n).suffix
    if ext not in MEDIA_EXTS:
        return False

    # Skip JSON, thumbnails, etc. Just in case the name is weird.
    if n.endswith(".json"):
        return False

    return True

def is_duplicate_variant(name: str) -> bool:
    """
    Skip noisy duplicate variants from Google Takeout, like:
      IMG_0861(1).mp4, IMG_0860(1).HEIC, etc.
    You can extend this if you ever see (2), (3), etc., but for now
    we're following your Option B: ignore the (1) versions.
    """
    stem = Path(name).stem.lower()
    return "(1)" in stem

def normalize_stem(name: str) -> str:
    """Get case-insensitive stem used for matching (no extension)."""
    return Path(name).stem.lower()

def scan_zip_media(zip_path: str):
    """
    Return:
      - zip_files: list of raw filenames in the ZIP (filtered to media, no (1))
      - stem_to_zip_names: mapping stem -> [filenames]
    """
    zip_files = []
    stem_to_zip_names = defaultdict(list)

    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            # Ignore directories
            if info.is_dir():
                continue

            name = info.filename
            base = Path(name).name  # strip folders inside the zip
            if not is_media_file(base):
                continue
            if is_duplicate_variant(base):
                continue

            zip_files.append(base)
            stem = normalize_stem(base)
            stem_to_zip_names[stem].append(base)

    return zip_files, stem_to_zip_names

def scan_icloud_media(icloud_dir: Path):
    """
    Return:
      - icloud_files: list of Paths
      - stem_to_icloud_paths: mapping stem -> [Paths]
    """
    icloud_files = []
    stem_to_icloud_paths = defaultdict(list)

    for p in icloud_dir.iterdir():
        if not p.is_file():
            continue
        if not is_media_file(p.name):
            continue

        icloud_files.append(p)
        stem = normalize_stem(p.name)
        stem_to_icloud_paths[stem].append(p)

    return icloud_files, stem_to_icloud_paths

def main():
    print("\n======= ZIP → iCloud RECONCILIATION (CLEANED) =======\n")
    print(f"📦 ZIP: {ZIP_PATH}")
    print(f"📱 iCloud Photos folder: {ICLOUD_DIR}\n")

    zip_files, stem_to_zip = scan_zip_media(ZIP_PATH)
    icloud_files, stem_to_icloud = scan_icloud_media(ICLOUD_DIR)

    print(f"🔍 Total media files in ZIP (after filtering JSON & (1) duplicates): {len(zip_files)}")
    print(f"📱 Total media files in iCloud Photos: {len(icloud_files)}\n")

    zip_stems = set(stem_to_zip.keys())
    icloud_stems = set(stem_to_icloud.keys())

    # 1) True missing: stems present in ZIP but completely absent from iCloud
    missing_stems = sorted(zip_stems - icloud_stems)

    # 2) Present but only in different extension(s)
    ext_mismatch = []  # list of (zip_name_example, [icloud_paths])
    for stem in sorted(zip_stems & icloud_stems):
        zip_names = stem_to_zip[stem]
        icloud_paths = stem_to_icloud[stem]

        zip_exts = {Path(n).suffix.lower() for n in zip_names}
        icloud_exts = {p.suffix.lower() for p in icloud_paths}

        # If there's no overlap in extensions at all, flag as an extension mismatch
        if zip_exts.isdisjoint(icloud_exts):
            ext_mismatch.append((zip_names[0], icloud_paths))

    # 3) Multi-format "families": stems where both zip + icloud have multiple variants
    multi_families = []
    for stem in sorted(zip_stems & icloud_stems):
        if len(stem_to_zip[stem]) + len(stem_to_icloud[stem]) > 2:
            multi_families.append(stem)

    # ---------- PRINT RESULTS ----------
    print("🚫 TRUE missing stems in iCloud (no matching filename at all by stem):", len(missing_stems))
    if missing_stems:
        print("    Examples:")
        for stem in missing_stems[:20]:
            names = stem_to_zip[stem]
            print("   ", ", ".join(names))
        if len(missing_stems) > 20:
            print(f"    ...(+{len(missing_stems) - 20} more)")
    else:
        print("    ✅ All ZIP stems are represented in iCloud (at least by stem).")

    print("\n🟥 Extension-only mismatches (same stem, different ext, no ext overlap):", len(ext_mismatch))
    if ext_mismatch:
        print("    Examples:")
        for zip_example, icloud_paths in ext_mismatch[:10]:
            icloud_names = [p.name for p in icloud_paths]
            print(f"    ZIP: {zip_example} → iCloud: {icloud_names}")
        if len(ext_mismatch) > 10:
            print(f"    ...(+{len(ext_mismatch) - 10} more)")

    print("\n📦 Multi-format families (stem has multiple variants between ZIP & iCloud):", len(multi_families))
    if multi_families:
        print("    Examples:")
        for stem in multi_families[:10]:
            print(f"    {stem} → ZIP: {stem_to_zip[stem]} | iCloud: {[p.name for p in stem_to_icloud[stem]]}")
        if len(multi_families) > 10:
            print(f"    ...(+{len(multi_families) - 10} more)")

    print("\n✅ Done.\n")

if __name__ == "__main__":
    main()
