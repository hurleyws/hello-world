import subprocess
import os
from pathlib import Path
from PIL import Image

# =========================
# CONFIG
# =========================
IMPORT_READY = Path(r"C:\Users\hurle\google_icloud\PhotoTransfer\import_ready")

# EXACT PATH to your FFmpeg executable
FFMPEG_EXE = Path(r"C:\Users\hurle\google_icloud\ffmpeg-2025-12-22-git-c50e5c7778-essentials_build\bin\ffmpeg.exe") 

def fix_video(input_path):
    """
    Attempts to fix video compatibility without altering color/quality.
    Strategy 1: REMUX (Copy stream to MP4 container) - Lossless.
    Strategy 2: TRANSCODE (If Remux fails) - Fallback to standard H.264.
    """
    output_path = input_path.with_suffix(".mp4")
    # Avoid name collision if file is already .mp4
    if output_path == input_path:
        output_path = input_path.with_stem(input_path.stem + "_fixed")

    print(f"🎥 Checking Video: {input_path.name}")

    # --- STRATEGY 1: REMUX (The "Better Way") ---
    # -c copy: Copies data exactly (NO color shift)
    # -movflags +faststart: Fixes iCloud web playback
    cmd_remux = [
        str(FFMPEG_EXE), "-y",
        "-i", str(input_path),
        "-c", "copy",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output_path)
    ]
    
    # Run silently
    res = subprocess.run(cmd_remux, capture_output=True)

    if res.returncode == 0:
        print("   ✅ Fixed via REMUX (Lossless).")
        try:
            input_path.unlink() # Delete old MOV
            if output_path.name != input_path.with_suffix(".mp4").name:
                 output_path.rename(input_path.with_suffix(".mp4"))
        except OSError:
            pass 
        return

    # --- STRATEGY 2: TRANSCODE (Fallback) ---
    print("   ⚠️ Remux failed (Codec incompatible). Transcoding...")
    
    cmd_transcode = [
        str(FFMPEG_EXE), "-y",
        "-i", str(input_path),
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]

    res = subprocess.run(cmd_transcode, capture_output=True)
    
    if res.returncode == 0:
        print("   ✅ Fixed via TRANSCODE.")
        try:
            input_path.unlink()
            if output_path.name != input_path.with_suffix(".mp4").name:
                 output_path.rename(input_path.with_suffix(".mp4"))
        except OSError:
            pass
    else:
        print(f"   ❌ FAILED. FFmpeg error.")

def fix_png(input_path):
    """
    Converts PNG to JPG to prevent iCloud viewer crashes on large screenshots.
    """
    print(f"🖼️  Checking Image: {input_path.name}")
    try:
        output_path = input_path.with_suffix(".jpg")
        
        with Image.open(input_path) as img:
            # Convert to RGB (PNGs can be RGBA which JPG doesn't support)
            rgb_im = img.convert('RGB')
            rgb_im.save(output_path, quality=95)
        
        print("   ✅ Converted to JPG.")
        input_path.unlink() # Delete original PNG
        
    except Exception as e:
        print(f"   ❌ Conversion Failed: {e}")

# =========================
# MAIN
# =========================
def main():
    if not FFMPEG_EXE.exists():
        print(f"❌ Error: FFmpeg not found at {FFMPEG_EXE}")
        return

    print(f"--- Scanning {IMPORT_READY} ---")

    # 1. Find Videos (.mov, .avi, etc)
    video_exts = {".mov", ".avi", ".3gp", ".m4v", ".mpg", ".flv", ".wmv"}
    videos = [p for p in IMPORT_READY.rglob("*") if p.suffix.lower() in video_exts]
    
    # 2. Find PNGs
    pngs = [p for p in IMPORT_READY.rglob("*") if p.suffix.lower() == ".png"]

    print(f"🔍 Found {len(videos)} videos and {len(pngs)} PNGs to fix.\n")

    for vid in videos:
        fix_video(vid)
        
    for png in pngs:
        fix_png(png)

    print("\n🎉 Cleanup Complete.")

if __name__ == "__main__":
    main()