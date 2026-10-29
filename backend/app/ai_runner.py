"""AI analysis runner (ARCHITECTURE.md §5).

A pool of worker threads (`ai_workers` setting, default 6) processes queued `ai_analyses` rows in parallel. The backend builds the full
context itself (context.py) so the CLI agents only need read access. Least privilege: commands never
include permission-bypass flags (enforced, also for commands configured in `settings`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from . import context, db

log = logging.getLogger("ielts.ai")

TIMEOUT_SEC = 15 * 60
INLINE_PROMPT_MAX = 24000      # agy has no stdin in print mode; longer prompts go via a file reference
SKILL_PATH = ".claude/skills/ielts-analysis/SKILL.md"

PROVIDERS = {
    "claude": {"name": "Claude Code"},
    "antigravity": {"name": "Antigravity"},
}
DEFAULT_COMMANDS: dict[str, list[str]] = {
    "claude": ["{exe}", "-p", "--output-format", "json", "--allowedTools", "Read Grep Glob"],
    "antigravity": ["{exe}", "-p", "{instruction}", "--output-format", "json", "--sandbox"],
}
FORBIDDEN_ARG_PATTERNS = re.compile(
    r"dangerously|bypass|skip-permissions|yolo|accept-?edits|--mode\b|--permission-mode|auto-?approve",
    re.IGNORECASE)

_wake = threading.Event()

_provider_cache: dict[str, Any] = {"at": 0.0, "data": None}
_provider_lock = threading.Lock()


# --------------------------------------------------------------------------- commands
def resolve_exe(provider: str, conn=None) -> str | None:
    override = db.get_setting(conn, f"ai_exe_{provider}") if conn is not None else None
    if override:
        return override if Path(override).exists() else shutil.which(override)
    if provider == "claude":
        return shutil.which("claude")
    if provider == "antigravity":
        p = Path.home() / ".gemini" / "bin" / ("agy.exe" if os.name == "nt" else "agy")
        return str(p) if p.exists() else shutil.which("agy")
    return None


def command_template(conn, provider: str) -> list[str]:
    raw = db.get_setting(conn, f"ai_cmd_{provider}")
    tpl = db.loads(raw) if raw else None
    if not isinstance(tpl, list) or not tpl or not all(isinstance(x, str) for x in tpl):
        tpl = DEFAULT_COMMANDS[provider]
    validate_command(tpl)
    return tpl


def validate_command(args: list[str]) -> None:
    for a in args:
        if FORBIDDEN_ARG_PATTERNS.search(a):
            raise ValueError(f"command argument {a!r} is not allowed (least-privilege policy)")


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    # allow running even when the server itself was started from inside a Claude Code session
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
        env.pop(k, None)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_quick(args: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, env=_child_env(),
                           stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        return p.returncode, (p.stdout or p.stderr).decode("utf-8", "replace").strip()
    except Exception as exc:
        return -1, str(exc)


def invalidate_provider_cache() -> None:
    _provider_cache["at"] = 0.0


def providers(force: bool = False) -> list[dict[str, Any]]:
    with _provider_lock:
        if not force and _provider_cache["data"] and time.time() - _provider_cache["at"] < 300:
            return _provider_cache["data"]
        with db.session(readonly=False) as conn:
            exes = {p: resolve_exe(p, conn) for p in PROVIDERS}
        out = []
        for pid, meta in PROVIDERS.items():
            exe = exes[pid]
            item = {"id": pid, "name": meta["name"], "available": False, "version": None, "path": exe}
            if exe:
                code, text = _run_quick([exe, "--version"])
                item["available"] = code == 0
                item["version"] = text.splitlines()[0] if text else None
                if code != 0:
                    item["error"] = text[-300:]
            out.append(item)
        _provider_cache.update(at=time.time(), data=out)
        return out


# --------------------------------------------------------------------------- prompt
def build_prompt(conn, row: dict) -> str:
    """Self-contained prompt: the skill's rules are embedded so no tool call is required.

    Antigravity in print mode can't be granted read-only file access without allowing shell commands,
    so it must be able to answer from the prompt alone. Claude may still Read KB pages if it wants.
    """
    ctx = context.build_context(conn, row["target_type"], row["target_id"], exclude_analysis=row["id"])
    skill = (db.ROOT / SKILL_PATH).read_text(encoding="utf-8")
    skill = re.sub(r"\A---.*?---\s*", "", skill, flags=re.DOTALL)  # drop front-matter
    return (
        "You are analysing an IELTS candidate's work. Everything you need is in this message: the analysis "
        "rules (<skill>) and the data from the local database (<context>). Do not run commands; answer "
        "directly. Respond ONLY with the report in the format the rules specify.\n\n"
        f"<skill>\n{skill}\n</skill>\n\n"
        f'<context target_type="{row["target_type"]}" target_id="{row["target_id"]}">\n'
        f"{ctx}\n</context>\n"
    )


# --------------------------------------------------------------------------- result parsing
_JSON_FENCE = re.compile(r"```json[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def split_report(text: str) -> tuple[str, dict | None]:
    """Split the final ```json fenced block off a markdown report."""
    matches = list(_JSON_FENCE.finditer(text or ""))
    if not matches:
        return (text or "").strip(), None
    m = matches[-1]
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return (text or "").strip(), None
    md = (text[:m.start()] + text[m.end():]).strip()
    return md, data if isinstance(data, dict) else {"data": data}


def parse_cli_output(provider: str, stdout: str) -> str:
    """Extract the model's final text from the CLI's --output-format json output."""
    s = (stdout or "").strip()
    if not s:
        raise RuntimeError("empty output")
    obj = None
    try:
        obj = json.loads(s)
    except ValueError:
        # some CLIs print log lines before the JSON; take the last JSON object line
        for line in reversed(s.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    break
                except ValueError:
                    continue
    if isinstance(obj, list):  # stream-like array: take the result event
        obj = next((o for o in reversed(obj) if isinstance(o, dict) and ("result" in o or "response" in o)), None)
    if not isinstance(obj, dict):
        return s  # fallback: raw text
    if obj.get("is_error") or (obj.get("subtype") and obj.get("subtype") != "success"):
        raise RuntimeError(f"{provider} reported an error: {str(obj.get('result') or obj)[:1000]}")
    status = str(obj.get("status") or "").upper()
    if status and status not in ("SUCCESS", "OK", "COMPLETED", "DONE"):
        raise RuntimeError(f"{provider} status {status}: {str(obj.get('response') or obj.get('error') or obj)[:1000]}")
    for key in ("result", "response", "text", "output", "content"):
        if isinstance(obj.get(key), str) and obj[key].strip():
            return obj[key]
    raise RuntimeError("no result text in CLI output: " + s[:500])


# --------------------------------------------------------------------------- execution
def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=_NO_WINDOW)
        else:
            proc.kill()
    except Exception:
        pass


def run_analysis(analysis_id: int) -> None:
    run_dir = db.AI_RUNS_DIR / str(analysis_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    with db.session() as conn:
        row = dict(conn.execute("SELECT * FROM ai_analyses WHERE id = ?", (analysis_id,)).fetchone())
        provider = row["provider"]
        if provider not in PROVIDERS:
            raise RuntimeError(f"unknown provider {provider!r}")
        prompt = build_prompt(conn, row)
        tpl = command_template(conn, provider)
        exe = resolve_exe(provider, conn)
        conn.execute("UPDATE ai_analyses SET prompt = ?, log_path = ? WHERE id = ?",
                     (prompt, str(run_dir.relative_to(db.ROOT) if run_dir.is_relative_to(db.ROOT) else run_dir),
                      analysis_id))
    if not exe:
        raise RuntimeError(f"{PROVIDERS[provider]['name']} CLI not found")
    prompt_file = run_dir / "prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    rel_prompt = prompt_file.relative_to(db.ROOT).as_posix() if prompt_file.is_relative_to(db.ROOT) \
        else prompt_file.as_posix()
    if len(prompt) <= INLINE_PROMPT_MAX:
        instruction = prompt
    else:
        instruction = (f"Read the file {rel_prompt} (relative to the current directory) and follow the "
                       "instructions in it exactly. Respond ONLY with the report.")
    args = [a.replace("{exe}", exe).replace("{prompt_file}", rel_prompt) if a != "{instruction}" else instruction
            for a in tpl]
    validate_command([a for a in args if a is not instruction])
    (run_dir / "command.json").write_text(
        json.dumps([a if a is not instruction else "<instruction>" for a in args], indent=1), encoding="utf-8")

    started = time.time()
    proc = subprocess.Popen(args, cwd=str(db.ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=_child_env(), creationflags=_NO_WINDOW)
    try:
        out, err = proc.communicate(input=prompt.encode("utf-8"), timeout=TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, err = proc.communicate()
        (run_dir / "stdout.txt").write_bytes(out or b"")
        (run_dir / "stderr.txt").write_bytes(err or b"")
        raise RuntimeError(f"timed out after {TIMEOUT_SEC // 60} minutes")
    (run_dir / "stdout.txt").write_bytes(out or b"")
    (run_dir / "stderr.txt").write_bytes(err or b"")
    stdout = (out or b"").decode("utf-8", "replace")
    stderr = (err or b"").decode("utf-8", "replace")
    log.info("analysis %s: %s exited %s in %.0fs", analysis_id, provider, proc.returncode, time.time() - started)
    try:
        text = parse_cli_output(provider, stdout)
    except RuntimeError as exc:
        raise RuntimeError(f"{exc} (exit {proc.returncode}; stderr: {stderr.strip()[-800:]})")
    if proc.returncode != 0 and not text.strip():
        raise RuntimeError(f"exit code {proc.returncode}: {stderr.strip()[-800:]}")
    md, data = split_report(text)
    (run_dir / "result.md").write_text(text, encoding="utf-8")
    with db.session() as conn:
        conn.execute("UPDATE ai_analyses SET status='done', result_md=?, result_json=?, error=NULL, "
                     "finished_at=? WHERE id=?", (md, db.dumps(data), db.now_iso(), analysis_id))


# --------------------------------------------------------------------------- queue
def _claim_next() -> int | None:
    with db.session() as conn:
        row = conn.execute("SELECT id FROM ai_analyses WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        cur = conn.execute("UPDATE ai_analyses SET status='running', started_at=? WHERE id=? AND status='queued'",
                           (db.now_iso(), row[0]))
        return row[0] if cur.rowcount else None


def _loop() -> None:
    while True:
        try:
            aid = _claim_next()
        except Exception:
            log.error("ai queue error\n%s", traceback.format_exc())
            aid = None
        if aid is None:
            _wake.wait(5)
            _wake.clear()
            continue
        try:
            run_analysis(aid)
        except Exception as exc:
            log.warning("analysis %s failed: %s", aid, exc)
            try:
                with db.session() as conn:
                    conn.execute("UPDATE ai_analyses SET status='error', error=?, finished_at=? WHERE id=?",
                                 (str(exc)[:4000], db.now_iso(), aid))
            except Exception:
                log.error("could not store analysis error\n%s", traceback.format_exc())


DEFAULT_WORKERS = 6  # parallel CLI runs; override with the `ai_workers` setting
_workers: list[threading.Thread] = []


def _worker_count() -> int:
    try:
        with db.session() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'ai_workers'").fetchone()
        return max(1, min(16, int(row[0]))) if row and row[0] else DEFAULT_WORKERS
    except Exception:
        return DEFAULT_WORKERS


def start_worker() -> None:
    """Start the worker pool (claiming a queued row is atomic, so workers never run the same analysis)."""
    _workers[:] = [w for w in _workers if w.is_alive()]
    for i in range(len(_workers), _worker_count()):
        w = threading.Thread(target=_loop, name=f"ielts-ai-runner-{i}", daemon=True)
        w.start()
        _workers.append(w)


def mark_stale_running() -> int:
    with db.session() as conn:
        cur = conn.execute("UPDATE ai_analyses SET status='error', error='interrupted: server restarted', "
                           "finished_at=? WHERE status='running'", (db.now_iso(),))
        return cur.rowcount


def enqueue(conn, target_type: str, target_id: int | None, provider: str) -> int:
    cur = conn.execute("INSERT INTO ai_analyses(target_type, target_id, provider, status, created_at) "
                       "VALUES (?,?,?, 'queued', ?)", (target_type, target_id or 0, provider, db.now_iso()))
    return cur.lastrowid


def wake() -> None:
    start_worker()
    _wake.set()
