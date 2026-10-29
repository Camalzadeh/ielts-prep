"""Download the practice tests (Cambridge IELTS 1-21 listening + reading) from engnovate.com.

The tests are not stored in the git repo (copyrighted Cambridge material, ~1.2 GB of audio); every user
downloads their own copy for personal study. Safe to stop (Ctrl+C) and re-run at any time: finished tests
are skipped and failed downloads are retried.

  Sources       https://engnovate.com/ielts-reading-tests/    https://engnovate.com/ielts-listening-tests/
  Saved to      content/tests/reading/*.json, content/tests/listening/*.json  (questions, passages, answers)
                content/media/listening/<test>/part1-4.mp3                      (audio)
                content/_cache/engnovate/                                       (raw pages, makes re-runs fast)

Usage: python tools/fetch_content.py [--no-audio] [--only cam15-reading-1 ...]
  --no-audio   skip the ~1.1 GB of audio; the listening player then streams it from engnovate (needs internet)
  --only       just these test ids (e.g. cam18-listening-2)
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "content" / "tests"


def step(n, total, text):
    print(f"\n=== [{n}/{total}] {text}", flush=True)


def summary() -> tuple[int, int, int, int]:
    reading = len(list((TESTS / "reading").glob("*.json")))
    listening = audio_have = audio_need = 0
    for f in (TESTS / "listening").glob("*.json"):
        listening += 1
        for part in json.loads(f.read_text(encoding="utf-8")).get("parts", []):
            if part.get("audio"):
                audio_need += 1
                audio_have += (ROOT / "content" / part["audio"]).exists()
    return reading, listening, audio_have, audio_need


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--only", nargs="*", default=[])
    args = ap.parse_args()
    py = sys.executable
    try:
        urllib.request.urlopen("https://engnovate.com/", timeout=15)
    except Exception as exc:
        sys.exit(f"Cannot reach engnovate.com ({exc}). Check your internet connection and run this again.")

    want_l = [t for t in args.only if "listening" in t]
    want_r = [t for t in args.only if "reading" in t]
    listening = [py, str(ROOT / "tools" / "scrape_engnovate_listening.py"), *[a for t in want_l for a in ("--only", t)]]
    if args.no_audio:
        listening.append("--no-audio")
    elif not shutil.which("ffmpeg"):
        print("Note: ffmpeg not found - keeping the original audio files (install ffmpeg to halve the disk use).")
        listening += ["--bitrate", "none"]
    reading = [py, str(ROOT / "tools" / "scrape_engnovate_reading.py")]
    if want_r:
        reading += ["--only", *want_r]

    t0 = time.time()
    step(1, 3, "Reading tests (about 140 tests, ~10 min). Free tests only; premium ones are skipped.")
    if want_r or not args.only:
        subprocess.run(reading, cwd=ROOT, check=False)
    step(2, 3, "Listening tests + audio (about 85 tests, ~1.1 GB; 20-60 min depending on your connection).")
    if want_l or not args.only:
        subprocess.run(listening, cwd=ROOT, check=False)
    step(3, 3, "Checking the downloaded tests")
    subprocess.run([py, str(ROOT / "tools" / "validate_tests.py")], cwd=ROOT, check=False)

    r, l, have, need = summary()
    print(f"\nDone in {(time.time() - t0) / 60:.0f} min: {r} reading tests, {l} listening tests, "
          f"audio {have}/{need} parts on disk.")
    if need and have < need and not args.no_audio:
        print("Some audio is missing (network hiccups). Run this again to fetch only what's missing - "
              "until then those parts stream from engnovate.")
    try:  # tell a running app to pick up the new tests
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8765/api/admin/reimport", method="POST"), timeout=5)
        print("The running app has re-imported the tests.")
    except Exception:
        print("Start the app with the IELTS Prep shortcut - the tests are imported automatically.")


if __name__ == "__main__":
    main()
