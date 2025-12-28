import subprocess
import os
import datetime
from pathlib import Path

# =========================
# CONFIG
# =========================
HOSPITAL_DIR = Path(r"C:\Users\hurle\google_icloud\video_hospital")
FFMPEG_EXE = Path(r"C:\Users\hurle\google_icloud\ffmpeg-2025-12-22-git-c50e5c7778-essentials_build\bin\ffmpeg.exe")
EXIFTOOL = Path(r"C:\Users\hurle\google_icloud\exiftool-13.43_64\exiftool.exe")

def heal_video(input_path, fixed_date_str):
    print(f"🚑 Healing: {input_path.name}")
    
    # 1. FORCE TRANSCODE (Re-bake to H.264)
    # This fixes the Grey Triangle / Missing Thumbnail
    output_path = input_path.with_stem(input_path.stem + "_fixed").with_suffix(".mp4")
    
    cmd = [
        str(FFMPEG_EXE), "-y",
        "-i", str(input_path),
        "-c:v", "libx264", "-preset", "slow", "-crf", "22", # High quality re-encode
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", # Maximum compatibility
        "-movflags", "+faststart",
        str(output_path)
    ]
    
    res = subprocess.run(cmd, capture_output=True)
    
    if res.returncode != 0:
        print(f"   ❌ FFmpeg Failed: {res.stderr.decode('utf-8')[-200:]}")
        return

    # 2. FORCE TIMESTAMP
    # Since these failed detection before, we brute-force the date you provide.
    ts_exif = f"{fixed_date_str}:01:01 12:00:00"
    
    cmd_exif = [
        str(EXIFTOOL), "-m", "-overwrite_original",
        f"-AllDates={ts_exif}",
        f"-QuickTime:CreateDate={ts_exif}", 
        f"-QuickTime:ModifyDate={ts_exif}",
        str(output_path)
    ]
    subprocess.run(cmd_exif, capture_output=True)
    
    # Fix file system date too
    fs_ts = ts_exif.replace(":", "-", 2)
    cmd_fs = [
        str(EXIFTOOL), "-m", "-overwrite_original",
        f"-FileModifyDate={fs_ts}", 
        f"-FileCreateDate={fs_ts}",
        str(output_path)
    ]
    subprocess.run(cmd_fs, capture_output=True)
    
    print(f"   ✅ Healed! Saved as: {output_path.name}")
    # Optional: Delete the broken original?
    # input_path.unlink()

def main():
    if not HOSPITAL_DIR.exists():
        HOSPITAL_DIR.mkdir(parents=True)
        print(f"Created {HOSPITAL_DIR}. Put your bad videos here and run again.")
        return

    videos = [p for p in HOSPITAL_DIR.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".avi", ".3gp", ".m4v"}]
    
    if not videos:
        print("No videos found in hospital folder.")
        return

    print(f"Found {len(videos)} patients in the hospital.")
    year = input("Enter the approximate YEAR for these videos (e.g. 2015): ")
    
    for vid in videos:
        if "_fixed" in vid.name: continue # Skip ones we already fixed
        heal_video(vid, year)

    print("\n🎉 All patients discharged.")

if __name__ == "__main__":
    main()