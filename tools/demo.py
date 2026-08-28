#!/usr/bin/env python3
"""tools/demo.py - both loops on the bundled fixtures, zero credentials.

    make demo
    python3 tools/demo.py

Forces `llm.provider=mock` and `mode=shadow` regardless of config/hotel.yaml
(`load_settings(demo=True)`), and runs against its own database
(`data/demo/demo.db`) so it never touches `data/agent.db`. The Notary is off
by default in `config/agent.yaml` (`subagents.compliance_gdpr.enabled:
false`) - this demo runs it anyway, once, so a fresh clone can see both
loops without editing config first; `make run` and `tools/gdpr.py` respect
the real setting.

Prints the line every check reads for the pass/fail signal:

    DEMO OK — 12 items processed, 12 drafted, 0 sent (shadow)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.adapters import get_email  # noqa: E402
from core.config import ConfigError, load_settings, sub_data_dir  # noqa: E402
from core.log import summary_line  # noqa: E402
from core.store import Store  # noqa: E402

import gdpr  # noqa: E402
import store_ext  # noqa: E402
from engine import load_drafts, process_draft  # noqa: E402


def main() -> int:
    try:
        settings = load_settings(demo=True)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    demo_db = sub_data_dir("demo") / "demo.db"
    if demo_db.exists():
        demo_db.unlink()  # every `make demo` is a clean, repeatable run
    store = Store(settings, path=demo_db)
    store_ext.migrate(store)

    drafts = load_drafts(settings, limit=50)
    if not drafts:
        print("no draft fixtures found in fixtures/inbound/ - nothing to demo", file=sys.stderr)
        return 1

    print(f"AI Manager / Overseer demo - {len(drafts)} draft(s) to screen, plus the Notary's "
         f"inbox check\n")
    print("Loop A - the Warden\n")
    counts = {"passed": 0, "blocked": 0, "held_rule": 0, "escalated": 0}
    for draft in drafts:
        item, _ = process_draft(settings, store, draft)
        counts[item.intent] = counts.get(item.intent, 0) + 1
        fired = ", ".join([*(item.draft or {}).get("escalated_by", []),
                          *(item.draft or {}).get("blocked_by", []),
                          *(item.draft or {}).get("held_by", [])]) or "-"
        print(f"  {draft['id']}: {draft.get('agent')} -> {draft.get('guest')}  "
             f"verdict={item.intent:<11} ({fired})")

    print(f"\n{counts['passed']} passed straight through, {counts['blocked']} blocked, "
         f"{counts['held_rule']} held, {counts['escalated']} escalated.")
    print("Duty-manager alerts on every blocked/escalated draft were attempted and blocked "
         "by shadow mode - see data/logs/*.jsonl.")

    messages = get_email(settings).fetch_unread(limit=50)
    print(f"\nLoop B - the Notary (off by default; run here too so the demo proves both "
         f"loops) - {len(messages)} sample email(s) checked\n")
    requests = gdpr.intake(settings, store)
    for request in requests:
        print(f"  {request.source_email_id}: {request.kind} request from {request.requester} "
             f"-> {request.id} ({gdpr.sla_days_left(request)} days left, "
             f"status={request.status})")
    print(f"\n{len(requests)} GDPR-shaped request(s) opened; "
         f"{len(messages) - len(requests)} email(s) were not GDPR-shaped and left for "
         f"whichever agent handles the guest inbox.")

    print("\nNothing was sent or delivered: mode is shadow, and demo never calls send() at all.")
    print("Next: `make review` to see what is waiting for a human, or read "
         "workflows/10-screening.md.\n")

    stats = {"processed": len(drafts) + len(requests), "drafted": len(drafts) + len(requests),
             "sent": 0}
    print(f"DEMO OK — {summary_line(stats, settings.mode)}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
