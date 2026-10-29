"""Read-only CLI over the IELTS database (for AI agents and the user).

Usage (from the project root):
  .venv\\Scripts\\python.exe tools\\ielts_db.py schema
  .venv\\Scripts\\python.exe tools\\ielts_db.py query "SELECT * FROM attempts LIMIT 5"
  .venv\\Scripts\\python.exe tools\\ielts_db.py attempt 12
  ... writing <id> | speaking <session_id> | mock <id> | progress | test <test_id> [--part N]
  ... kb-search "<words>" | kb <slug>

The database is opened with a `mode=ro` URI, so nothing can be modified.
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import context, db  # noqa: E402


def _utf8_stdout() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, io.UnsupportedOperation):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))


def _print_rows(cur: sqlite3.Cursor, max_rows: int) -> None:
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchmany(max_rows + 1)
    if not cols:
        print("(no result set)")
        return
    print("\t".join(cols))
    for r in rows[:max_rows]:
        print("\t".join("" if v is None else str(v).replace("\n", "\\n") for v in r))
    if len(rows) > max_rows:
        print(f"... (truncated at {max_rows} rows; use --max-rows)")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    p = argparse.ArgumentParser(prog="ielts_db", description="Read-only IELTS DB helper")
    p.add_argument("--db", default=str(db.DB_PATH), help="database path")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema")
    q = sub.add_parser("query")
    q.add_argument("sql")
    q.add_argument("--max-rows", type=int, default=200)
    q.add_argument("--json", action="store_true")
    for name in ("attempt", "writing", "speaking", "mock"):
        sp = sub.add_parser(name)
        sp.add_argument("id", type=int)
    sub.add_parser("progress")
    t = sub.add_parser("test")
    t.add_argument("test_id")
    t.add_argument("--part", type=int)
    t.add_argument("--no-answers", action="store_true")
    ks = sub.add_parser("kb-search")
    ks.add_argument("q", nargs="+")
    k = sub.add_parser("kb")
    k.add_argument("slug")
    args = p.parse_args(argv)

    if not Path(args.db).is_file():
        print(f"database not found: {args.db} (start the backend once to create it)", file=sys.stderr)
        return 2
    conn = db.connect(readonly=True, path=Path(args.db))
    try:
        if args.cmd == "schema":
            print(context.schema_text(conn))
        elif args.cmd == "query":
            sql = args.sql.strip().rstrip(";")
            if not sql.lower().startswith(("select", "with", "pragma table_info", "explain")):
                print("only SELECT / WITH queries are allowed", file=sys.stderr)
                return 2
            cur = conn.execute(sql)
            if args.json:
                cols = [d[0] for d in cur.description or []]
                print(json.dumps([dict(zip(cols, r)) for r in cur.fetchmany(args.max_rows)],
                                 ensure_ascii=False, indent=1))
            else:
                _print_rows(cur, args.max_rows)
        elif args.cmd == "attempt":
            print(context.attempt_context(conn, args.id))
        elif args.cmd == "writing":
            print(context.writing_context(conn, args.id))
        elif args.cmd == "speaking":
            print(context.speaking_context(conn, args.id))
        elif args.cmd == "mock":
            print(context.mock_context(conn, args.id))
        elif args.cmd == "progress":
            print(context.progress_context(conn))
        elif args.cmd == "test":
            print(context.test_text(conn, args.test_id, args.part, with_answers=not args.no_answers))
        elif args.cmd == "kb-search":
            rows = context.kb_search(conn, " ".join(args.q))
            for r in rows:
                print(f"{r['slug']}\t[{r['category']}] {r['title']}\n    {r['snippet']}")
            if not rows:
                print("(no matches)")
        elif args.cmd == "kb":
            d = context.kb_doc(conn, args.slug)
            if not d:
                print(f"no kb doc {args.slug!r}", file=sys.stderr)
                return 1
            print(f"# {d['title']}\ncategory: {d['category']} | tags: {d['tags']} | path: knowledge/kb/{d['path']}\n")
            print(d["content_md"])
    except sqlite3.Error as exc:
        print(f"sqlite error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
