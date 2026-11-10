"""Desktop launcher (Windows + Linux): start the IELTS Prep server if it isn't running, then open it in an app window.

Windows: run with pythonw (no console). Linux: run with the venv python (the .desktop file does this).
Server output goes to data/server.log.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8765"
HEALTH = URL + "/api/health"
WINDOWS = os.name == "nt"
VENV_PY = ROOT / ".venv" / ("Scripts/pythonw.exe" if WINDOWS else "bin/python")


def healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def start_server():
    log_dir = ROOT / "data"
    log_dir.mkdir(exist_ok=True)
    log = open(log_dir / "server.log", "ab")
    kwargs = dict(cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
    if WINDOWS:
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True  # keep running after the launcher exits
    subprocess.Popen([str(VENV_PY if VENV_PY.exists() else sys.executable), str(ROOT / "backend" / "run.py")], **kwargs)


def find_browser():
    """A Chromium-based browser supports --app (a clean window without tabs/address bar)."""
    if WINDOWS:
        candidates = [
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return shutil.which("msedge") or shutil.which("chrome")
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
        if shutil.which(name):
            return shutil.which(name)
    return None


# Edge opens its own "mini menu" (Copy, Search, Copilot...) over selected text, on top of the app's popup
# (Highlight / Clear / Translate). Pages cannot suppress it, so it is switched off in the app's own browser
# profile (not in the user's normal Edge). Edge reads it at start; Chrome has no such menu.
BROWSER_PREFS = {"edge_quick_search": {"show_mini_menu": False, "PDF_show_mini_menu": False}}


def quiet_browser_menus(profile: Path) -> None:
    prefs = profile / "Default" / "Preferences"
    try:
        data = json.loads(prefs.read_text(encoding="utf-8")) if prefs.is_file() else {}
        changed = False
        for section, values in BROWSER_PREFS.items():
            cur = data.setdefault(section, {})
            for k, v in values.items():
                if cur.get(k) != v:
                    cur[k] = v
                    changed = True
        if changed:
            prefs.parent.mkdir(parents=True, exist_ok=True)
            prefs.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # never block opening the app over a preference


def show_error(msg: str):
    if WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "IELTS Prep", 0x10)
    elif shutil.which("zenity"):
        subprocess.run(["zenity", "--error", "--title=IELTS Prep", f"--text={msg}"])
    else:
        print(msg, file=sys.stderr)


def main():
    if not healthy():
        start_server()
        for _ in range(120):  # first start imports content; give it up to 60 s
            if healthy():
                break
            time.sleep(0.5)
        else:
            show_error(f"The server did not start. See {ROOT / 'data' / 'server.log'}")
            return
    browser = find_browser()
    if browser:
        # a dedicated profile keeps the microphone permission and window size
        profile = ROOT / "data" / "browser-profile"
        quiet_browser_menus(profile)
        args = [browser, f"--app={URL}", f"--user-data-dir={profile}", "--window-size=1440,900"]
        if WINDOWS:
            subprocess.Popen(args, creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(URL)


if __name__ == "__main__":
    main()
