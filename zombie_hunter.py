import zipfile
import subprocess
import os
import shutil
import re
from pathlib import Path

# =========================
# CONFIG
# =========================
TAKEOUT_DIR = Path(r"E:") 
FFPROBE_EXE = Path(r"C:\Users\hurle\google_icloud\ffmpeg-2025-12-22-git-c50e5c7778-essentials_build\bin\ffprobe.exe")
TEMP_DIR = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\temp_xray")

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".m4v", ".3gp"}

def get_video_codec(file_path):
    try:
        cmd = [
            str(FFPROBE_EXE), 
            "-v", "error", 
            "-select_streams", "v:0", 
            "-show_entries", "stream=codec_name", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.strip().lower()
    except Exception:
        return "error"

def get_zip_path(zip_num):
    for z in TAKEOUT_DIR.glob("*.zip"):
        match = re.search(r'-(\d+)\.zip$', z.name)
        if match and int(match.group(1)) == int(zip_num):
            return z
    return None

def main():
    print("--- 🩺 ZIP VIDEO X-RAY ---")
    
    if not FFPROBE_EXE.exists():
        print("❌ Error: FFprobe not found.")
        return

    # 1. Get ZIP
    user_input = input("Enter ZIP number to audit (e.g. 2): ")
    zip_path = get_zip_path(user_input)
    
    if not zip_path:
        print(f"❌ ZIP #{user_input} not found.")
        return

    # 2. Scan ZIP for Videos
    print(f"📦 Scanning {zip_path.name}...")
    video_files = []
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            if not name.endswith('/') and Path(name).suffix.lower() in VIDEO_EXTS:
                video_files.append(name)
    
    if not video_files:
        print("✅ No videos found in this ZIP.")
        return

    print(f"🔍 Found {len(video_files)} videos. Extracting to temp for scanning...")
    
    # 3. Extract & Scan
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    hevc_count = 0
    safe_count = 0
    error_count = 0
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            for i, v_name in enumerate(video_files, 1):
                # Extract single file
                z.extract(v_name, TEMP_DIR)
                local_path = TEMP_DIR / v_name
                
                # Check Codec
                codec = get_video_codec(local_path)
                
                if "hevc" in codec or "hvc1" in codec or "hev1" in codec:
                    print(f"  ⚠️ HEVC Found: {Path(v_name).name} ({codec})")
                    hevc_count += 1
                elif codec == "error":
                    print(f"  ❌ Error reading: {Path(v_name).name}")
                    error_count += 1
                else:
                    # Optional: Print safe ones? Usually too much noise.
                    # print(f"  ✅ Safe: {Path(v_name).name} ({codec})")
                    safe_count += 1
                
                # Delete immediately to save space
                if local_path.exists():
                    local_path.unlink()
                    
                if i % 10 == 0:
                    print(f"  ...scanned {i}/{len(video_files)}")
                    
    finally:
        # Cleanup any folders created by extraction
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)

    # 4. Report
    print(f"\n{'='*60}")
    print(f"RESULTS FOR ZIP #{user_input}")
    print(f"{'='*60}")
    print(f"   • Total Videos: {len(video_files)}")
    print(f"   • Safe (H.264): {safe_count}")
    print(f"   • Suspect (HEVC): {hevc_count}")
    print(f"   • Errors: {error_count}")
    
    if hevc_count > 0:
        print("\n💡 ADVICE: This ZIP contains HEVC videos.")
        print("   If you want to avoid 'Grey Triangles' on iCloud Web,")
        print("   ensure your main script uses the 'check_needs_transcode' logic.")
    else:
        print("\n✅ All videos appear to be safe/compatible.")

if __name__ == "__main__":
    main()