"""Download the practice tests (Cambridge IELTS listening + reading from engnovate.com) for personal study.

The tests are not stored in the git repo (copyrighted material, ~1.2 GB of audio); every user fetches
their own copy once. Both scrapers are resumable - re-run this to fill in anything that failed.

Usage: python tools/fetch_content.py [--no-audio]
  --no-audio   skip the ~1.1 GB of listening audio; the player then streams it from engnovate (needs internet)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-audio", action="store_true")
    args = ap.parse_args()
    py = sys.executable
    listening = [py, str(ROOT / "tools" / "scrape_engnovate_listening.py")]
    if args.no_audio:
        listening.append("--no-audio")
    elif not shutil.which("ffmpeg"):
        print("ffmpeg not found: keeping the original audio files (install ffmpeg to save ~50% disk space)")
        listening += ["--bitrate", "none"]
    for cmd in ([py, str(ROOT / "tools" / "scrape_engnovate_reading.py")], listening):
        print(">", " ".join(Path(c).name if i else c for i, c in enumerate(cmd)), flush=True)
        subprocess.run(cmd, cwd=ROOT, check=False)
    print("Done. Start the app (desktop shortcut / launcher) - new tests are imported automatically.")


if __name__ == "__main__":
    main()
