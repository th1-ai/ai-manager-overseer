#!/usr/bin/env python3
"""tools/run.py - the Warden's screening loop: fetch -> screen -> queue/clear.

    python3 tools/run.py --once
    python3 tools/run.py --watch
    python3 tools/run.py --once --dry-run
    python3 tools/run.py --once --limit 5

One pass: read every pending draft another agent produced (config/agent.yaml:
draft_feed), skip anything already screened, run `tools/engine.py:
screen_draft()` on each, and either clear it (`auto_sent`) or queue it for a
human (`needs_human`) with the duty manager notified on a block/escalation.
The Warden never drafts a reply itself and never sends one - see
docs/how-it-works.md and workflows/10-screening.md.

Exit codes: 0 ok, 1 a real error. There is no `interactive` LLM call on this
path (screening is deterministic) so exit code 3 never happens here - see
tools/digest.py for the one prompt in this repo.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.log import Run, get_logger, summary_line  # noqa: E402
from core.store import Store  # noqa: E402

from engine import load_drafts, process_draft  # noqa: E402

log = get_logger("run")


def one_pass(settings, store, *, limit: int) -> dict:
    stats = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0, "skipped": 0}
    with Run("screening", settings, store) as run:
        drafts = load_drafts(settings, limit=limit)
        seen = store.already_processed("draft_feed", [str(d["id"]) for d in drafts])
        for draft in drafts:
            if str(draft["id"]) in seen:
                stats["skipped"] += 1
                continue
            item, did_work = process_draft(settings, store, draft)
            if not did_work:
                stats["skipped"] += 1
                continue
            stats["processed"] += 1
            stats["drafted"] += 1
            if item.review_status == "needs_human":
                stats["needs_human"] += 1
            log.info("screened", item_id=item.id, verdict=item.intent, status=item.review_status)
        reaped = store.reap_stuck_sending()
        if reaped:
            log.warn("reaped stuck sends", count=len(reaped))
        run.stats = dict(stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--once", action="store_true", help="run a single pass (default)")
    mode_group.add_argument("--watch", action="store_true",
                            help="keep running on the configured interval")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute everything, write nothing, even in live mode")
    parser.add_argument("--limit", type=int, default=50, help="max drafts per pass")
    parser.add_argument("--poll-seconds", type=int, default=None,
                        help="override the --watch interval (default: agent.yaml or 120)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    # --dry-run is a rehearsal: compute everything, write nothing - not even
    # to this repo's own data/agent.db. An ephemeral in-memory database gives
    # process_draft() somewhere real to write during the pass (so the code
    # path - upsert_item / set_fields / transition - runs exactly as normal)
    # while guaranteeing nothing lands on disk and nothing from one
    # --dry-run pass can collide with the next (no rows, no IntegrityError,
    # ever - each pass starts from empty). See factory/workflows/build-repo.md
    # section 5 ("--dry-run writes nothing") and docs/safety.md.
    store = Store(settings, path=":memory:" if settings.dry_run else None)
    try:
        if args.watch:
            poll_seconds = args.poll_seconds or int(settings.agent_get("poll_seconds", 120))
            while True:
                stats = one_pass(settings, store, limit=args.limit)
                print(summary_line(stats, settings.mode))
                time.sleep(poll_seconds)
        stats = one_pass(settings, store, limit=args.limit)
        print(summary_line(stats, settings.mode))
        return 0
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
