"""Background speech transcription with faster-whisper + fluency metrics.

One worker thread, one lazily loaded model, int8 on CPU, model cache in data/models. Preferred model is
"small.en" with "base.en" as fallback. On a fresh install the smaller base.en is downloaded first so the
first recording is transcribed quickly; small.en is then downloaded in the background and used as soon
as it is complete. Audio is converted to 16 kHz mono wav with ffmpeg first.
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import traceback
from pathlib import Path
from typing import Any

from . import db

# Must be set before huggingface_hub is imported (lazily, via faster_whisper). The Xet transfer backend
# was observed to stall indefinitely on this machine; plain HTTP downloads resume reliably.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

log = logging.getLogger("ielts.transcribe")
DOWNLOAD_TIMEOUT_SEC = 20 * 60

MODEL_CANDIDATES = ("small.en", "base.en")   # best first
PAUSE_SEC = 0.6
LONG_PAUSE_SEC = 1.5
LOW_PROB = 0.5
FILLER_WORDS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "mm"}
# "like" is only a filler when set off by commas ("it was, like, huge") - not "what I like most"
FILLER_PHRASES = ("you know", "i mean", "sort of", "kind of")
INITIAL_PROMPT = "Umm, let me think, uh... well, like, you know, I mean, er, it's hard to say."

_queue: "queue.Queue[int]" = queue.Queue()
_worker: threading.Thread | None = None
_model = None
_model_name: str | None = None
_model_error: str | None = None
_model_lock = threading.Lock()
_downloads: dict[str, concurrent.futures.Future] = {}   # name -> future(local path)
_downloads_lock = threading.Lock()


# --------------------------------------------------------------------------- model
def _local_path(name: str) -> str | None:
    """Path of a fully downloaded model in data/models, else None (no network access)."""
    from faster_whisper.utils import download_model
    try:
        return download_model(name, local_files_only=True, cache_dir=str(db.MODELS_DIR))
    except Exception:
        return None


def _download(name: str) -> concurrent.futures.Future:
    """Start (once) a background download in a daemon thread; a stalled download can't block the worker."""
    with _downloads_lock:
        fut = _downloads.get(name)
        if fut is not None and not (fut.done() and fut.exception() is not None):
            return fut
        fut = concurrent.futures.Future()
        _downloads[name] = fut

    def run() -> None:
        from faster_whisper.utils import download_model
        try:
            log.info("downloading whisper model %s ...", name)
            fut.set_result(download_model(name, cache_dir=str(db.MODELS_DIR)))
            log.info("whisper model %s downloaded", name)
        except BaseException as exc:  # noqa: BLE001 - forwarded to the waiter
            log.warning("download of %s failed: %s", name, exc)
            fut.set_exception(exc)

    threading.Thread(target=run, name=f"whisper-download-{name}", daemon=True).start()
    return fut


def _load(name: str, path: str):
    from faster_whisper import WhisperModel
    global _model, _model_name, _model_error
    _model = WhisperModel(path, device="cpu", compute_type="int8")
    _model_name, _model_error = name, None
    log.info("loaded whisper model %s", name)
    return _model


def get_model():
    global _model_error
    with _model_lock:
        try:
            import faster_whisper  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on env
            _model_error = f"faster-whisper not importable: {exc}"
            raise RuntimeError(_model_error)
        best = MODEL_CANDIDATES[0]
        if _model is not None:
            if _model_name != best:          # upgrade once the better model finished downloading
                fut = _downloads.get(best)
                if fut is not None and fut.done() and fut.exception() is None:
                    try:
                        return _load(best, fut.result())
                    except Exception as exc:
                        log.warning("could not load %s: %s", best, exc)
            return _model
        errors = []
        for name in MODEL_CANDIDATES:        # best model already on disk?
            path = _local_path(name)
            if path:
                try:
                    model = _load(name, path)
                    if name != best:
                        _download(best)
                    return model
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
        # nothing usable locally: fetch the smallest first, then the best one in the background
        for name in reversed(MODEL_CANDIDATES):
            try:
                path = _download(name).result(timeout=DOWNLOAD_TIMEOUT_SEC)
                model = _load(name, path)
                if name != best:
                    _download(best)
                return model
            except concurrent.futures.TimeoutError:
                errors.append(f"{name}: download timed out after {DOWNLOAD_TIMEOUT_SEC // 60} min")
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        _model_error = "; ".join(errors)
        raise RuntimeError(_model_error)


def model_info() -> dict[str, Any]:
    return {"loaded": _model is not None, "name": _model_name, "error": _model_error,
            "queue": _queue.qsize(), "ffmpeg": shutil.which("ffmpeg") is not None,
            "downloads": {n: ("running" if not f.done() else "error" if f.exception() else "done")
                          for n, f in list(_downloads.items())}}


# --------------------------------------------------------------------------- audio + metrics
def to_wav(src: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    tmp = src.with_name(src.stem + ".16k.tmp.wav")
    proc = subprocess.run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-i", str(src),
                           "-ac", "1", "-ar", "16000", "-f", "wav", str(tmp)],
                          capture_output=True, timeout=300)
    if proc.returncode != 0:
        Path(tmp).unlink(missing_ok=True)
        raise RuntimeError("ffmpeg failed: " + proc.stderr.decode("utf-8", "replace")[-500:])
    return Path(tmp)


def _read_wav(path: Path):
    """16 kHz mono s16 wav -> float32 numpy array. Passing an array avoids faster-whisper's PyAV decoder,
    which is incompatible with the installed PyAV ("unexpected keyword argument 'metadata_errors'")."""
    import wave

    import numpy as np
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getframerate() != 16000:
            raise RuntimeError("unexpected wav format from ffmpeg")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _clean_word(w: str) -> str:
    return re.sub(r"[^a-z']", "", w.lower())


def count_fillers(words: list[str]) -> dict[str, int]:
    clean = [_clean_word(w) for w in words]
    found: dict[str, int] = {}
    for i, w in enumerate(clean):
        if w in FILLER_WORDS:
            found[w] = found.get(w, 0) + 1
        elif w == "like" and (words[i].rstrip().endswith(",") or (i and words[i - 1].rstrip().endswith(","))):
            found[w] = found.get(w, 0) + 1
    joined = " " + " ".join(clean) + " "
    for phrase in FILLER_PHRASES:
        c = joined.count(" " + phrase + " ")
        if c:
            found[phrase] = c
    return found


def compute_metrics(words: list[dict], duration: float | None) -> dict[str, Any]:
    """words: [{word, start, end, probability}] (whisper)."""
    tokens = [w["word"].strip() for w in words if w.get("word", "").strip()]
    n = len(tokens)
    if not duration and words:
        duration = words[-1]["end"]
    duration = round(float(duration or 0), 2)
    gaps = []
    for prev, cur in zip(words, words[1:]):
        gap = (cur.get("start") or 0) - (prev.get("end") or 0)
        if gap > PAUSE_SEC:
            gaps.append({"start": round(prev["end"], 2), "duration": round(gap, 2)})
    fillers = count_fillers(tokens)
    speech_time = (words[-1]["end"] - words[0]["start"]) if words else 0
    return {
        "duration": duration,
        "words": n,
        "wpm": round(n / duration * 60, 1) if duration else None,
        "articulation_wpm": round(n / speech_time * 60, 1) if speech_time > 0 else None,
        "pause_count": len(gaps),
        "long_pauses": sum(1 for g in gaps if g["duration"] > LONG_PAUSE_SEC),
        "pauses": gaps[:50],
        "filler_count": sum(fillers.values()),
        "fillers": fillers,
        "low_confidence_words": [
            {"word": w["word"].strip(), "start": round(w["start"], 2), "end": round(w["end"], 2),
             "probability": round(w["probability"], 2)}
            for w in words if (w.get("probability") is not None and w["probability"] < LOW_PROB)
        ],
    }


def text_metrics(text: str | None, duration: float | None) -> dict[str, Any]:
    """Fallback metrics from a plain (browser) transcript: no pause/confidence info."""
    tokens = (text or "").split()
    fillers = count_fillers(tokens)
    return {"duration": duration, "words": len(tokens),
            "wpm": round(len(tokens) / duration * 60, 1) if duration else None,
            "pause_count": None, "long_pauses": None, "filler_count": sum(fillers.values()),
            "fillers": fillers, "low_confidence_words": [], "source": "browser"}


def transcribe_file(path: Path) -> dict[str, Any]:
    model = get_model()
    wav = to_wav(path)
    try:
        segments, info = model.transcribe(_read_wav(wav), language="en", beam_size=5, word_timestamps=True,
                                          vad_filter=False, condition_on_previous_text=False,
                                          initial_prompt=INITIAL_PROMPT)
        segs, words = [], []
        for s in segments:
            sw = [{"word": w.word, "start": round(w.start, 2), "end": round(w.end, 2),
                   "probability": round(w.probability, 3)} for w in (s.words or [])]
            words.extend(sw)
            segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                         "avg_logprob": round(s.avg_logprob, 3), "no_speech_prob": round(s.no_speech_prob, 3),
                         "words": sw})
        text = " ".join(s["text"] for s in segs).strip()
        return {"model": _model_name, "duration": round(info.duration, 2), "language": info.language,
                "text": text, "segments": segs, "words": words}
    finally:
        wav.unlink(missing_ok=True)


# --------------------------------------------------------------------------- jobs
def process_response(response_id: int) -> None:
    with db.session() as conn:
        r = conn.execute("SELECT * FROM speaking_responses WHERE id = ?", (response_id,)).fetchone()
        if not r:
            return
        r = dict(r)
    path = db.UPLOADS_DIR / (r["audio_path"] or "")
    try:
        if not r["audio_path"] or not path.is_file():
            raise FileNotFoundError(f"audio file missing: {path}")
        result = transcribe_file(path)
        duration = r["duration_sec"] or result["duration"]
        metrics = compute_metrics(result["words"], duration)
        metrics["model"] = result["model"]
        transcript = result["text"] or r["browser_transcript"]
        with db.session() as conn:
            conn.execute("UPDATE speaking_responses SET transcript=?, whisper_json=?, metrics_json=?, "
                         "transcribe_status='done', duration_sec=COALESCE(duration_sec, ?) WHERE id=?",
                         (transcript, db.dumps(result), db.dumps(metrics), result["duration"], response_id))
    except Exception as exc:
        log.warning("transcription failed for response %s: %s\n%s", response_id, exc, traceback.format_exc())
        unavailable = isinstance(exc, RuntimeError) and (
            "faster-whisper" in str(exc) or "ffmpeg not found" in str(exc) or _model is None)
        status = "unavailable" if unavailable else "error"
        with db.session() as conn:
            conn.execute("UPDATE speaking_responses SET transcript=COALESCE(browser_transcript, transcript), "
                         "whisper_json=?, metrics_json=COALESCE(metrics_json, ?), transcribe_status=? WHERE id=?",
                         (db.dumps({"error": str(exc)}),
                          db.dumps(text_metrics(r["browser_transcript"], r["duration_sec"])),
                          status, response_id))


def _run() -> None:
    while True:
        rid = _queue.get()
        try:
            process_response(rid)
        except Exception:
            log.error("transcribe worker error\n%s", traceback.format_exc())
        finally:
            _queue.task_done()


def start_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_run, name="ielts-transcriber", daemon=True)
    _worker.start()


def enqueue(response_id: int) -> None:
    start_worker()
    _queue.put(response_id)


def requeue_pending() -> int:
    with db.session() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM speaking_responses WHERE transcribe_status = 'pending' ORDER BY id")]
    for i in ids:
        enqueue(i)
    return len(ids)
