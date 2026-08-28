#!/usr/bin/env python3
"""tools/report.py - what the Warden and the Notary caught, and what it cost.

    make report
    python3 tools/report.py
    python3 tools/report.py --json

Reads data/agent.db only - nothing here calls a model or an adapter. Every
number is tied to a roster claim (README.md section 2 and docs/benefits.md):

``screening``   drafts screened, by verdict - the roster claims "<1 bad
                message ever reaching a guest"; this is the honest,
                measured version: how many were caught, not a guess at how
                many got through (docs/how-it-works.md design decision 9).
``interventions`` share of screened drafts that were NOT passed straight
                through - blocked, held or escalated.
``privacy``     open GDPR requests by status, and the tightest deadline.
``spend``       LLM calls, tokens and cost (the one call is the daily note).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.config import ConfigError, load_settings  # noqa: E402
from core.store import Store  # noqa: E402

import store_ext  # noqa: E402
from gdpr import sla_days_left  # noqa: E402


def screening(store: Store) -> dict:
    rows = store.db.execute(
        "SELECT intent, COUNT(*) AS n FROM items WHERE kind='draft' GROUP BY intent").fetchall()
    by_verdict = {r["intent"] or "unknown": r["n"] for r in rows}
    total = sum(by_verdict.values())
    interventions = total - by_verdict.get("passed", 0)
    rate = (interventions / total) if total else 0.0
    return {"by_verdict": by_verdict, "total": total, "interventions": interventions,
           "intervention_rate": rate}


def privacy(store: Store) -> dict:
    requests = store_ext.list_gdpr_requests(store)
    by_status = {}
    for request in requests:
        by_status[request.status] = by_status.get(request.status, 0) + 1
    open_requests = [r for r in requests if r.status != "done"]
    nearest = min((sla_days_left(r) for r in open_requests), default=None)
    breached = sum(1 for r in open_requests if sla_days_left(r) < 0)
    return {"total": len(requests), "by_status": by_status, "open": len(open_requests),
           "nearest_deadline_days": nearest, "breached": breached}


def spend(store: Store) -> dict:
    return store.usage_totals()


def build_report(store: Store) -> dict:
    return {"screening": screening(store), "privacy": privacy(store), "spend": spend(store)}


def print_report(report: dict) -> None:
    s = report["screening"]
    print("AI Manager / Overseer - report\n")
    print(f"Screened: {s['total']} draft(s) total")
    if s["by_verdict"]:
        print("  by verdict: " + ", ".join(f"{k}={n}" for k, n in sorted(s["by_verdict"].items())))
    print(f"Interventions: {s['interventions']}/{s['total']} draft(s) were held, blocked or "
         f"escalated ({s['intervention_rate']*100:.0f}%) - everything else went straight "
         f"through with no human touch.")

    p = report["privacy"]
    print(f"\nPrivacy queue: {p['open']} open of {p['total']} request(s) ever seen"
         + (f", nearest deadline in {p['nearest_deadline_days']} day(s)" if p["nearest_deadline_days"] is not None else "")
         + (f", {p['breached']} breached" if p["breached"] else "") + ".")

    sp = report["spend"]
    print(f"\nSpend: {sp['calls']} LLM call(s) (the daily governance note), "
         f"{sp['input_tokens']} input + {sp['output_tokens']} output token(s), "
         f"USD {sp['cost_usd']:.4f}.")
    if sp["calls"] and sp["cost_usd"] == 0.0:
        print("  (0.00 is expected on provider=mock, interactive or claude-code - only "
             "the anthropic provider bills per token.)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store_ext.migrate(store)
    try:
        report = build_report(store)
    finally:
        store.close()

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
