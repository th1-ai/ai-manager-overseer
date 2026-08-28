#!/usr/bin/env python3
"""tools/digest.py - the daily governance note: the one LLM call in this repo.

    python3 tools/digest.py
    make schedule ARGS="--all"    # see it listed under schedule.daily_digest

This is what "runs the daily review loop" means here (docs/how-it-works.md
design decision 6): a few sentences of prose, once a day, summarising what
the Warden and the Notary already decided with real code. The prompt
(`prompts/governance-note.md`) is told to use only the JSON it is given and
never invent a name, a number or a rule - see the system prompt itself.

Exit codes: 0 ok, 3 waiting on an `interactive` answer, 1 a real error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.llm import LLMError, LLMPendingInteractive, complete  # noqa: E402
from core.store import Store  # noqa: E402
from core.templates import build_prompt  # noqa: E402

import store_ext  # noqa: E402
from gdpr import sla_days_left  # noqa: E402

SCHEMA = json.loads((REPO_ROOT / "prompts" / "schemas" / "governance-note.json")
                    .read_text(encoding="utf-8"))


def build_summary(store: Store) -> dict:
    rows = store.db.execute(
        "SELECT intent, COUNT(*) AS n FROM items WHERE kind='draft' GROUP BY intent").fetchall()
    counts = {r["intent"] or "unknown": r["n"] for r in rows}
    return {"screened": sum(counts.values()), "passed": counts.get("passed", 0),
           "blocked": counts.get("blocked", 0), "held_rule": counts.get("held_rule", 0),
           "escalated": counts.get("escalated", 0)}


def recent_events(store: Store, limit: int = 10) -> list[dict]:
    rows = store.db.execute(
        "SELECT payload_json, intent, draft_json FROM items WHERE kind='draft' "
        "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        draft = json.loads(row["draft_json"] or "{}")
        out.append({"agent": payload.get("agent"), "verdict": row["intent"],
                   "why": draft.get("detail")})
    return out


def privacy_queue(store: Store, limit: int = 6) -> list[dict]:
    open_requests = [r for r in store_ext.list_gdpr_requests(store) if r.status != "done"]
    return [{"id": r.id, "kind": r.kind, "days_left": sla_days_left(r)}
           for r in open_requests[:limit]]


def run_digest(settings: Settings, store: Store, *, provider: str | None = None) -> str:
    body = {"summary": build_summary(store), "recent_events": recent_events(store),
           "privacy_queue": privacy_queue(store)}
    prompt = build_prompt("governance-note", settings=settings, item=body,
                          fixture_id="governance-note-01")
    result = complete("governance-note", prompt, SCHEMA, settings=settings, provider=provider,
                      store=store, fixture_id="governance-note-01")
    note = (result.data or {}).get("note", "")
    store.record_event(None, "agent", "governance_note", {"note": note, "summary": body["summary"]})
    return note


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default=None, help="override llm.provider for this run")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(provider=args.provider)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store_ext.migrate(store)
    try:
        note = run_digest(settings, store, provider=args.provider)
    except LLMPendingInteractive as exc:
        print(str(exc))
        return 3
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()

    print("Today's governance note:\n")
    print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
