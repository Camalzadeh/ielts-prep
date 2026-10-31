import time

import pytest
from fastapi.testclient import TestClient

from backend.app import ai_runner, context, db, importer
from backend.app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        for _ in range(100):  # startup import runs in a background thread
            if not importer.status()["running"] and importer.status()["last_finished"]:
                break
            time.sleep(0.1)
        # results in the archive fixtures are attributed via the user_name setting
        c.put("/api/settings", json={"user_name": "TestUser"})
        importer.run_import()
        yield c


def test_health_and_import(client):
    assert client.get("/api/health").json()["ok"]
    st = client.get("/api/admin/status").json()
    c = st["counts"]
    assert c["tests"] == 2
    assert c["writing_prompts"] == 4          # 3 curated + 1 created from my_essays
    assert c["writing_submissions"] == 3      # 2 my_essays + 1 new photo essay (other one merged)
    assert c["external_results"] == 3         # StudentA + group table expanded (TestUser, StudentB)
    assert c["speaking_questions"] == 13
    assert c["vocab"] == 3
    assert c["kb_docs"] == 2
    assert any("broken.json" in e for e in st["import"]["errors"])
    pe = st["import"]["last_result"]["photo_essays"]
    # the fixture re-runs the import after setting user_name, so the new essay now counts as merged
    assert pe == {"essays": 3, "mine": 2, "inserted": 0, "merged": 2}
    subs = client.get("/api/writing/submissions?origin=telegram_import").json()
    merged = [s for s in subs if s["teacher_band"] == 6.0]
    assert len(merged) == 1 and merged[0]["created_at"].startswith("2026-07-28")
    full = client.get(f"/api/writing/submissions/{merged[0]['id']}").json()
    assert full["teacher_comments"] == "Good position; develop examples."
    stats = client.get("/api/stats").json()
    assert stats["baseline"]["overall"] == 6.0 and stats["baseline"]["person"] == "TestUser"
    assert any(p["source"] == "teacher" for p in stats["bands_over_time"]["writing"])
    with db.session(readonly=True) as conn:
        assert "External results" in context.progress_context(conn)
    # idempotent
    r = client.post("/api/admin/reimport?wait=1").json()
    assert r["result"]["my_essays"]["inserted"] == 0
    assert client.get("/api/admin/status").json()["counts"] == c


def test_attempt_flow(client):
    tests = client.get("/api/tests?type=listening").json()
    assert tests[0]["id"] == "fixture-listening-1" and tests[0]["question_count"] == 10
    t = client.get("/api/tests/fixture-listening-1").json()
    assert "answer" not in t["parts"][0]["groups"][0]["questions"][0]
    assert "transcript_html" not in t["parts"][0]
    assert t["parts"][0]["audio_url"]
    assert client.get("/api/tests/fixture-listening-1/review").status_code == 403

    aid = client.post("/api/attempts", json={"test_id": "fixture-listening-1", "mode": "practice"}).json()["id"]
    assert client.put(f"/api/attempts/{aid}/autosave", json={"answers": {"1": "x"}}).json() == {"ok": True}
    res = client.post(f"/api/attempts/{aid}/submit", json={
        "answers": {"1": "Jamieson", "2": "parking", "3": "1500", "4": "lake", "5": "B",
                    "6": "B", "7": "D", "8": "A", "9": "B", "10": "family"},
        "duration_sec": 1500}).json()
    assert res["raw_score"] == 9 and res["total"] == 10
    assert [d["number"] for d in res["details"] if not d["is_correct"]] == [4]
    assert client.post(f"/api/attempts/{aid}/submit", json={"answers": {}}).status_code == 409
    full = client.get(f"/api/attempts/{aid}").json()
    assert full["test"]["title"] and len(full["details"]) == 10
    assert client.get("/api/tests/fixture-listening-1/review").json()["parts"][0]["groups"][0]["questions"][0]["answer"]
    assert client.get("/api/tests?type=listening").json()[0]["attempts"] == 1

    with db.session(readonly=True) as conn:
        ctx = context.attempt_context(conn, aid)
    assert "Q4" in ctx and "lake" in ctx and "river" in ctx.lower()


def test_writing_flow(client):
    p = client.get("/api/writing/prompts/random?task=1").json()
    assert p["image_url"] == "/media/content/writing/fixture.png"
    r = client.post("/api/writing/submissions", json={"prompt_id": p["id"], "text": "The graph shows sales.",
                                                      "time_spent_sec": 600}).json()
    assert r["word_count"] == 4
    s = client.get(f"/api/writing/submissions/{r['id']}").json()
    assert s["prompt"]["id"] == p["id"]
    with db.session(readonly=True) as conn:
        assert "UNDER LENGTH" in context.writing_context(conn, r["id"])


def test_speaking_and_mock(client):
    rs = client.get("/api/speaking/random-set?mode=full").json()
    assert len(rs["part1"]) >= 9 and rs["part2"]["cue_points"] and rs["part3"][0]["topic"] == "Films"
    sid = client.post("/api/speaking/sessions", json={"mode": "full", "plan": rs}).json()["id"]
    r = client.post("/api/speaking/responses", data={"session_id": sid, "part": 1, "question_text": "Q?",
                                                     "duration_sec": 6, "browser_transcript": "um I like music"}).json()
    assert r["transcribe_status"] == "unavailable"
    sess = client.get(f"/api/speaking/sessions/{sid}").json()
    assert sess["responses"][0]["metrics"]["filler_count"] == 1   # "um" ("I like music" is a verb, not a filler)

    m = client.post("/api/mock", json={"sections": ["listening", "reading", "writing", "speaking"]}).json()
    assert m["plan"]["reading"] == "fixture-reading-1"
    aid = client.post("/api/attempts", json={"test_id": "fixture-reading-1", "mode": "mock", "mock_id": m["id"]}).json()["id"]
    client.post(f"/api/attempts/{aid}/submit", json={"answers": {"1": "FALSE"}})
    assert client.post(f"/api/mock/{m['id']}/link", json={"section": "speaking", "ref_id": sid}).json()["ok"]
    with db.session() as conn:  # fake a finished AI analysis for the speaking session
        conn.execute("INSERT INTO ai_analyses(target_type, target_id, provider, status, result_json) "
                     "VALUES ('speaking_session', ?, 'claude', 'done', '{\"band\": 6.5}')", (sid,))
    fin = client.post(f"/api/mock/{m['id']}/finish").json()
    assert fin["bands"]["speaking"] == 6.5 and fin["bands"]["reading"] is not None
    assert "writing" in fin["missing"] and "listening" in fin["missing"]
    assert fin["bands"]["overall"] is None            # not all four sections have bands
    got = client.get(f"/api/mock/{m['id']}").json()
    assert got["links"]["speaking"] == [sid] and got["live_bands"]["overall"] is None
    assert got["overall_band"] is None
    # a mock planned with only reading gets an overall as soon as reading is banded
    m2 = client.post("/api/mock", json={"sections": ["reading"]}).json()
    a2 = client.post("/api/attempts", json={"test_id": "fixture-reading-1", "mock_id": m2["id"]}).json()["id"]
    client.post(f"/api/attempts/{a2}/submit", json={"answers": {"1": "FALSE", "2": "TRUE"}})
    assert client.post(f"/api/mock/{m2['id']}/finish").json()["bands"]["overall"] is not None


def test_kb_vocab_stats_settings(client):
    assert {d["slug"] for d in client.get("/api/kb").json()} == {"task2-structure", "linking-words"}
    assert client.get("/api/kb/search?q=paragraphs").json()[0]["slug"] == "task2-structure"
    assert client.get("/api/kb/task2-structure").json()["tags"] == "task2, structure"
    v = client.get("/api/vocab?due=1").json()
    r = client.post(f"/api/vocab/{v[0]['id']}/review", json={"grade": 5}).json()
    assert r["reps"] == 1 and r["interval_days"] == 1
    s = client.get("/api/stats").json()
    assert s["counts"]["listening_attempts"] >= 1 and s["by_question_type"]
    assert s["streak_days"] >= 1
    assert client.put("/api/settings", json={"ai_provider": "antigravity"}).json()["ai_provider"] == "antigravity"
    bad = client.put("/api/settings", json={"ai_cmd_claude": ["{exe}", "--dangerously-skip-permissions"]})
    assert bad.status_code == 422


def test_ai_helpers():
    md, data = ai_runner.split_report("# Report\ntext\n```json\n{\"band\": 6.5, \"tips\": []}\n```\n")
    assert md == "# Report\ntext" and data["band"] == 6.5
    assert ai_runner.parse_cli_output("claude", '{"type":"result","subtype":"success","is_error":false,"result":"hi"}') == "hi"
    assert ai_runner.parse_cli_output("antigravity", '{"status":"SUCCESS","response":"PONG\\n"}') == "PONG\n"
    with pytest.raises(RuntimeError):
        ai_runner.parse_cli_output("claude", '{"type":"result","subtype":"error_max_turns","is_error":true}')
    for flag in ("--dangerously-skip-permissions", "--permission-mode", "--yolo", "--mode"):
        with pytest.raises(ValueError):
            ai_runner.validate_command(["x", flag])
    ai_runner.validate_command(ai_runner.DEFAULT_COMMANDS["claude"])
    ai_runner.validate_command(["agy", "--model", "x"])


def test_codex_provider(client, tmp_path, monkeypatch):
    for pid, tpl in ai_runner.DEFAULT_COMMANDS.items():
        ai_runner.validate_command(tpl)
        assert pid in ai_runner.PROVIDERS and ai_runner.PROVIDERS[pid]["install"]
    assert "{output_file}" in ai_runner.DEFAULT_COMMANDS["codex"] and "{instruction}" not in ai_runner.DEFAULT_COMMANDS["codex"]
    for flag in ("--full-auto", "danger-full-access", "workspace-write", 'sandbox_mode="danger-full-access"', "approval_policy=never"):
        with pytest.raises(ValueError):
            ai_runner.validate_command(["codex", "exec", flag])
    assert client.put("/api/settings", json={"ai_cmd_codex": ["{exe}", "exec", "--full-auto", "-"]}).status_code == 422
    assert client.put("/api/settings", json={"ai_provider": "codex"}).json()["ai_provider"] == "codex"
    client.put("/api/settings", json={"ai_provider": "claude"})
    # the answer comes from {output_file}; stdout only has progress logs
    tpl, out = ai_runner.DEFAULT_COMMANDS["codex"], tmp_path / "last_message.md"
    with pytest.raises(RuntimeError, match="wrote no answer"):
        ai_runner.read_answer("codex", tpl, out, 1, "codex: thinking…", "not logged in")
    out.write_text("# Report\nok\n", encoding="utf-8")
    assert ai_runner.read_answer("codex", tpl, out, 0, "progress log", "") == "# Report\nok"
    assert ai_runner.read_answer("claude", ai_runner.DEFAULT_COMMANDS["claude"], out, 0, '{"result":"hi"}', "") == "hi"
    # end to end with a stand-in CLI: prompt on stdin, answer written to --output-last-message
    fake = tmp_path / "fake_codex.py"
    fake.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "assert args[:3] == ['exec', '--sandbox', 'read-only'] and args[-1] == '-', args\n"
        "prompt = sys.stdin.read()\n"
        "assert '<skill>' in prompt and '<context' in prompt\n"
        "print('codex progress log')\n"
        "out = args[args.index('--output-last-message') + 1]\n"
        "open(out, 'w', encoding='utf-8').write('# Progress\\nfine\\n```json\\n{\"band\": 6.5}\\n```\\n')\n",
        encoding="utf-8")
    import sys
    client.put("/api/settings", json={"ai_exe_codex": sys.executable,
                                      "ai_cmd_codex": ["{exe}", str(fake)] + ai_runner.DEFAULT_COMMANDS["codex"][1:]})
    with db.session() as conn:
        aid = ai_runner.enqueue(conn, "progress", 0, "codex")
    ai_runner.run_analysis(aid)
    row = client.get(f"/api/ai/analyses/{aid}").json()
    assert row["status"] == "done" and row["result"]["band"] == 6.5 and "fine" in row["result_md"]
    client.put("/api/settings", json={"ai_exe_codex": None, "ai_cmd_codex": None})
    # not installed -> listed as unavailable with an install hint
    monkeypatch.setattr(ai_runner, "resolve_exe", lambda p, conn=None: None)
    listed = {p["id"]: p for p in client.get("/api/ai/providers?refresh=true").json()}
    assert listed["codex"]["available"] is False and "npm install -g @openai/codex" in listed["codex"]["install"]
    ai_runner.invalidate_provider_cache()


def test_speaking_delete_response(client):
    sid = client.post("/api/speaking/sessions", json={"mode": "practice_part1", "plan": {}}).json()["id"]
    keep, drop = (client.post("/api/speaking/responses", files={"audio": ("a.webm", b"x", "audio/webm")},
                              data={"session_id": sid, "part": 1, "question_text": q}).json()["id"]
                  for q in ("Q1", "Q2"))
    with db.session() as conn:
        path = db.UPLOADS_DIR / conn.execute("SELECT audio_path FROM speaking_responses WHERE id=?", (drop,)).fetchone()[0]
    assert client.delete(f"/api/speaking/responses/{drop}").json()["ok"]
    assert [r["id"] for r in client.get(f"/api/speaking/sessions/{sid}").json()["responses"]] == [keep]
    assert not path.exists()
    assert client.delete(f"/api/speaking/responses/{drop}").status_code == 404


def test_delete_attempt_and_transcript(client):
    from backend.app.routers.tests import evidence_excerpt
    assert evidence_excerpt('<p><b>From the transcript:</b> “usually about eight people but no more than ten”</p>'
                            '<p>other</p>') == "usually about eight people but no more than ten"
    # reading: the passage quote, several sentences joined
    assert evidence_excerpt('<p>Why…</p><p><strong>Evidence from the passage:</strong></p><blockquote>'
                            '<p>a Welshman who amassed a fortune</p><p>in the shipping &amp; mining industries</p></blockquote>'
                            ) == "a Welshman who amassed a fortune … in the shipping & mining industries"
    assert evidence_excerpt("<p>no quote</p>") is None and evidence_excerpt(None) is None

    aid = client.post("/api/attempts", json={"test_id": "fixture-listening-1", "mode": "practice"}).json()["id"]
    t = client.get(f"/api/attempts/{aid}/transcript?part=1").json()
    assert "Jamieson" in t["transcript_html"] and t["part"] == 1
    assert client.get(f"/api/attempts/{aid}/transcript?part=9").status_code == 404
    client.post(f"/api/attempts/{aid}/submit", json={"answers": {"1": "Jamieson"}})
    assert "excerpt" in client.get(f"/api/attempts/{aid}").json()["details"][0]
    with db.session() as conn:
        conn.execute("INSERT INTO ai_analyses(target_type, target_id, provider, status) VALUES ('attempt', ?, 'claude', 'done')", (aid,))
    assert client.delete(f"/api/attempts/{aid}").json() == {"ok": True, "id": aid}
    assert client.get(f"/api/attempts/{aid}").status_code == 404
    assert client.delete(f"/api/attempts/{aid}").status_code == 404
    with db.session(readonly=True) as conn:
        assert not conn.execute("SELECT 1 FROM attempt_answers WHERE attempt_id=?", (aid,)).fetchone()
        assert not conn.execute("SELECT 1 FROM ai_analyses WHERE target_type='attempt' AND target_id=?", (aid,)).fetchone()

    # exam mode: no transcript; deleting a mock section clears the mock's stored bands
    m = client.post("/api/mock", json={"sections": ["listening"]}).json()
    mid = client.post("/api/attempts", json={"test_id": "fixture-listening-1", "mode": "mock", "mock_id": m["id"]}).json()["id"]
    assert client.get(f"/api/attempts/{mid}/transcript?part=1").status_code == 403
    client.post(f"/api/attempts/{mid}/submit", json={"answers": {"1": "Jamieson"}})
    client.post(f"/api/mock/{m['id']}/finish")
    client.delete(f"/api/attempts/{mid}")
    mk = client.get(f"/api/mock/{m['id']}").json()
    assert mk["listening_band"] is None and mk["overall_band"] is None

    # reading has no transcript; imported results are managed in My Results.docx
    rid = client.post("/api/attempts", json={"test_id": "fixture-reading-1"}).json()["id"]
    assert client.get(f"/api/attempts/{rid}/transcript?part=1").status_code == 422
    with db.session() as conn:
        conn.execute("UPDATE attempts SET mode='imported' WHERE id=?", (rid,))
    assert client.delete(f"/api/attempts/{rid}").status_code == 409
    with db.session() as conn:
        conn.execute("DELETE FROM attempts WHERE id=?", (rid,))


def test_delete_writing_and_speaking(client):
    # essay written in the app: deleted with its analyses; its mock loses the writing band
    p = client.get("/api/writing/prompts/random?task=2").json()
    m = client.post("/api/mock", json={"sections": ["writing"]}).json()
    sub = client.post("/api/writing/submissions", json={"prompt_id": p["id"], "text": "Some essay text.", "mock_id": m["id"]}).json()["id"]
    with db.session() as conn:
        conn.execute("INSERT INTO ai_analyses(target_type, target_id, provider, status) VALUES ('writing', ?, 'claude', 'done')", (sub,))
        conn.execute("UPDATE mock_exams SET writing_band=6, overall_band=6 WHERE id=?", (m["id"],))
    assert client.delete(f"/api/writing/submissions/{sub}").json() == {"ok": True, "id": sub}
    assert client.get(f"/api/writing/submissions/{sub}").status_code == 404
    assert client.delete(f"/api/writing/submissions/{sub}").status_code == 404
    with db.session(readonly=True) as conn:
        assert not conn.execute("SELECT 1 FROM ai_analyses WHERE target_type='writing' AND target_id=?", (sub,)).fetchone()
        assert tuple(conn.execute("SELECT writing_band, overall_band FROM mock_exams WHERE id=?", (m["id"],)).fetchone()) == (None, None)
    # essays imported from the course chat stay (the next import would bring them back)
    imported = client.get("/api/writing/submissions?origin=telegram_import").json()[0]["id"]
    assert client.delete(f"/api/writing/submissions/{imported}").status_code == 409

    # speaking session: recordings, their files and analyses go too
    sid = client.post("/api/speaking/sessions", json={"mode": "practice_part1", "plan": {}}).json()["id"]
    rid = client.post("/api/speaking/responses", files={"audio": ("a.webm", b"x", "audio/webm")},
                      data={"session_id": sid, "part": 1, "question_text": "Q1"}).json()["id"]
    with db.session() as conn:
        audio = conn.execute("SELECT audio_path FROM speaking_responses WHERE id=?", (rid,)).fetchone()[0]
        conn.execute("INSERT INTO ai_analyses(target_type, target_id, provider, status) VALUES ('speaking_session', ?, 'claude', 'done')", (sid,))
    assert (db.UPLOADS_DIR / audio).exists()
    assert client.delete(f"/api/speaking/sessions/{sid}").json() == {"ok": True, "id": sid}
    assert client.get(f"/api/speaking/sessions/{sid}").status_code == 404
    assert not (db.UPLOADS_DIR / audio).exists()
    with db.session(readonly=True) as conn:
        assert not conn.execute("SELECT 1 FROM speaking_responses WHERE session_id=?", (sid,)).fetchone()
        assert not conn.execute("SELECT 1 FROM ai_analyses WHERE target_type='speaking_session' AND target_id=?", (sid,)).fetchone()
    with db.session() as conn:
        imp = conn.execute("INSERT INTO speaking_sessions(created_at, mode, teacher_band) VALUES ('2026-08-01', 'imported', 6)").lastrowid
    assert client.delete(f"/api/speaking/sessions/{imp}").status_code == 409
    with db.session() as conn:
        conn.execute("DELETE FROM speaking_sessions WHERE id=?", (imp,))


def test_general_training_hidden_by_default(client):
    from backend.app.routers.mock import pick_test
    with db.session() as conn:
        conn.execute("INSERT INTO tests(id, type, module, title, data_json) VALUES "
                     "('gt-reading-x', 'reading', 'general', 'GT test', '{\"parts\": []}')")
    ids = lambda **q: {t["id"] for t in client.get("/api/tests", params={"type": "reading", **q}).json()}
    assert client.get("/api/settings").json()["show_general_training"] == "0"
    assert "gt-reading-x" not in ids() and "fixture-reading-1" in ids()
    assert "gt-reading-x" in ids(module="general")
    # a test already started (or submitted) stays in the library
    aid = client.post("/api/attempts", json={"test_id": "gt-reading-x"}).json()["id"]
    assert "gt-reading-x" in ids()
    client.delete(f"/api/attempts/{aid}")
    assert "gt-reading-x" not in ids()
    client.put("/api/settings", json={"show_general_training": "1"})
    assert "gt-reading-x" in ids()
    client.put("/api/settings", json={"show_general_training": "0"})
    # mocks: Academic only, whatever the setting
    with db.session(readonly=True) as conn:
        assert {pick_test(conn, "reading", "academic") for _ in range(20)} == {"fixture-reading-1"}
        assert pick_test(conn, "reading", "general") == "gt-reading-x"
    with db.session() as conn:
        conn.execute("DELETE FROM tests WHERE id='gt-reading-x'")
