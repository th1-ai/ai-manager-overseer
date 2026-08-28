#!/usr/bin/env python3
"""tools/review.py - work the Warden's queue: list / show / release / reject,
plus pause / resume an agent (simulated) and the go-live `stale` step.

    python3 tools/review.py list [--status needs_human]
    python3 tools/review.py show <id>
    python3 tools/review.py release <id> [--note "..."]   # "Release the hold"
    python3 tools/review.py reject <id> --reason "..."     # the block stands
    python3 tools/review.py pause "Front Desk AI" --reason "..."
    python3 tools/review.py resume "Front Desk AI"
    python3 tools/review.py fleet                          # who is paused right now
    python3 tools/review.py stale                           # go-live step

A screened draft never gets a second AI answer drafted for it - the Warden
only ever holds or clears what another agent already wrote. "Release the
hold" is the one write this tool performs, and it goes through the same
`core.review` guard as every send in the family: blocked in `mode: shadow`,
recorded either way. Only this tool writes `approved` / `sent` / `rejected`
on a screened item - see docs/how-it-works.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.adapters import get_messaging  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.log import get_logger  # noqa: E402
from core.review import WriteBlocked, list_queue, reject, show, stale_backlog  # noqa: E402
from core.store import Store, StoreError  # noqa: E402

import store_ext  # noqa: E402

log = get_logger("review")


def _print_item_line(item) -> None:
    payload = item.payload or {}
    # `item.is_sample` is set by core (core/store.py) for anything read
    # through a mock adapter outside `make demo` - see docs/integrations.md
    # "Sample data is labelled".
    marker = "  [SAMPLE DATA]" if item.is_sample else ""
    print(f"  {item.id}  {item.review_status:<14} {item.intent or '-':<11} "
         f"{payload.get('agent', '-'):<20} {payload.get('guest', '-')}{marker}")


def cmd_list(store, args) -> int:
    items = list_queue(store, status=args.status, kind="draft", limit=args.limit)
    if not items:
        print("Nothing is waiting for you.")
        return 0
    print(f"{len(items)} item(s) waiting:\n")
    for item in items:
        _print_item_line(item)
    print("\nRun `python3 tools/review.py show <id>` for the full draft and evidence.")
    return 0


def cmd_show(store, args) -> int:
    try:
        detail = show(store, args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    item = detail["item"]
    payload = item.get("payload") or {}
    draft = item.get("draft") or {}
    if payload.get("_sample"):
        print("[SAMPLE DATA] this item was read through a mock adapter, not your "
             "property - see docs/integrations.md.\n")
    print(f"{item['id']}  verdict={item.get('intent')}  status={item['review_status']}")
    print(f"Agent: {payload.get('agent', '-')}   Channel: {payload.get('channel', '-')}   "
         f"Guest: {payload.get('guest', '-')}")
    if payload.get("draft_text"):
        print(f"\nThe agent's draft:\n{payload['draft_text']}")
    if draft.get("detail"):
        print(f"\nThe Warden's verdict:\n{draft['detail']}")
    print(f"\nFull evidence:\n{json.dumps(draft, indent=2, ensure_ascii=False)}")
    events = detail["events"]
    if events:
        print("\nEvents:")
        for event in events:
            print(f"  {event['ts']}  {event['actor']:<6} {event['action']}")
    return 0


def cmd_release(store, settings, args) -> int:
    """"Release the hold" - a human checked it and it may now go out.

    This tool does not own the guest channel (the originating agent does),
    so the only real write here is the duty-manager confirmation, and it is
    guarded exactly like the original hold notification: blocked in
    `mode: shadow`, recorded either way. The decision itself (`approved`) is
    always recorded, in or out of shadow - see docs/how-it-works.md.
    """
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    try:
        item = store.transition(item.id, "approved", "human", {"note": args.note or ""})
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    payload = item.payload or {}
    text = (f"[Warden] hold released by a human on {item.id} - {payload.get('agent', 'an agent')}'s "
           f"draft to {payload.get('guest', 'a guest')} may now go out.")
    try:
        get_messaging(settings).notify_staff(text, item=item)
        store.record_event(item.id, "human", "hold_released", {"note": args.note or "", "notified": True})
        log.info("released", item_id=item.id, actor="human", notified=True, note=args.note or None)
        print(f"released {item.id} - recorded, and the duty manager was notified.")
    except WriteBlocked as exc:
        store.record_event(item.id, "human", "hold_released", {"note": args.note or "", "notified": False})
        log.warn("released", item_id=item.id, actor="human", notified=False, reason=str(exc))
        print(f"released {item.id} - recorded on the audit trail.")
        print(f"  -> {exc}")
    except AdapterError as exc:
        store.record_event(item.id, "human", "hold_released", {"note": args.note or "", "notified": False})
        log.warn("released", item_id=item.id, actor="human", notified=False, error=str(exc))
        print(f"released {item.id}, but the duty-manager notification failed: {exc}")
    return 0


def cmd_reject(store, args) -> int:
    item = reject(store, args.id, reason=args.reason or "")
    log.info("rejected", item_id=item.id, actor="human", reason=args.reason or None)
    print(f"rejected {item.id} - the hold stands.")
    return 0


def cmd_pause(store, args) -> int:
    status = store_ext.pause_agent(store, args.agent, actor="human", reason=args.reason or "")
    log.info("paused", agent=args.agent, actor="human", reason=args.reason or None)
    print(f"{args.agent}: paused (simulated) - {status.get('paused_at')}")
    print("In production this genuinely takes the agent off the field until you resume it. "
         "Here it only marks the state, since this repo cannot reach another agent's process.")
    return 0


def cmd_resume(store, args) -> int:
    status = store_ext.resume_agent(store, args.agent, actor="human")
    log.info("resumed", agent=args.agent, actor="human")
    print(f"{args.agent}: active again - {status.get('resumed_at')}")
    return 0


def cmd_fleet(store, args) -> int:
    rows = store_ext.list_fleet(store)
    if not rows:
        print("No agent has ever been paused from here.")
        return 0
    for row in rows:
        print(f"  {row['agent_name']:<24} {row['status']:<8} "
             f"paused_by={row['paused_by'] or '-'} reason={row['paused_reason'] or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="what is waiting for a human")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="full detail for one screened draft")
    p_show.add_argument("id")

    p_release = sub.add_parser("release", help='"Release the hold" - a human checked it')
    p_release.add_argument("id")
    p_release.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="the block stands; nothing changes")
    p_reject.add_argument("id")
    p_reject.add_argument("--reason", "--note", dest="reason", default="")

    p_pause = sub.add_parser("pause", help="pause an agent (simulated - see the help text above)")
    p_pause.add_argument("agent")
    p_pause.add_argument("--reason", default="")

    p_resume = sub.add_parser("resume", help="resume a paused agent (simulated)")
    p_resume.add_argument("agent")

    sub.add_parser("fleet", help="who is paused right now")
    sub.add_parser("stale", help="go-live step: mark every un-released hold as stale")

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store_ext.migrate(store)
    try:
        if args.command == "list":
            return cmd_list(store, args)
        if args.command == "show":
            return cmd_show(store, args)
        if args.command == "release":
            return cmd_release(store, settings, args)
        if args.command == "reject":
            return cmd_reject(store, args)
        if args.command == "pause":
            return cmd_pause(store, args)
        if args.command == "resume":
            return cmd_resume(store, args)
        if args.command == "fleet":
            return cmd_fleet(store, args)
        if args.command == "stale":
            moved = stale_backlog(store)
            log.info("stale_backlog", actor="human", moved=len(moved))
            print(f"marked {len(moved)} item(s) stale. Nothing from before go-live releases "
                 f"by surprise.")
            return 0
        parser.error(f"unknown command {args.command}")
        return 2
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
