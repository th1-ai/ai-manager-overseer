#!/usr/bin/env python3
"""tools/gdpr.py - the Notary's request desk: intake, checklist, sign-off.

    python3 tools/gdpr.py intake                 # scan the inbox for GDPR-shaped mail
    python3 tools/gdpr.py list [--status open]
    python3 tools/gdpr.py show <id>
    python3 tools/gdpr.py step <id>               # do the next undone checklist step
    python3 tools/gdpr.py run <id>                # do every step up to (not including) sign-off
    python3 tools/gdpr.py assign <id> --to counsel
    python3 tools/gdpr.py signoff <id>            # the human gate - see docs/how-it-works.md
    python3 tools/gdpr.py sweep                   # SLA digest; the scheduled job

Every request is worked one checklist step at a time, each with its own
`done_at`/`done_by` (docs/how-it-works.md design decision 13), and the last
step of every checklist is a synthetic human sign-off that no automated
command can complete (design decision 17) - "a human signs off before
anything leaves" is enforced here, not just promised in the README.

No model call anywhere in this file - the whole flow is deterministic, which
is the right choice for a statutory process (specs/compliance-gdpr-ai.md
section 7).
"""

from __future__ import annotations

import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.adapters import get_email, get_messaging  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, Settings, load_settings, repo_root  # noqa: E402
from core.log import get_logger  # noqa: E402
from core.review import WriteBlocked  # noqa: E402
from core.store import Store, StoreError, utcnow  # noqa: E402

import store_ext  # noqa: E402
from store_ext import GdprRequest  # noqa: E402

log = get_logger("gdpr")

DEFAULT_SYSTEMS = ("the PMS, the email and WhatsApp archive, the folio and invoice store, "
                   "the marketing list, and the Wi-Fi captive-portal logs")
KINDS = ("erasure", "access", "rectification")


class GdprError(RuntimeError):
    """Raised for a request in the wrong state for the command given. Readable, no traceback."""


def _read_knowledge(rel_path: str) -> str:
    """A knowledge/ path, falling back to its shipped ``.example.md`` twin."""
    path = repo_root() / rel_path
    if not path.exists() and rel_path.endswith(".md") and not rel_path.endswith(".example.md"):
        path = repo_root() / rel_path.replace(".md", ".example.md")
    return path.read_text(encoding="utf-8") if path.exists() else ""


# --------------------------------------------------------------------------
# intake
# --------------------------------------------------------------------------
def load_intake_phrases(text: str) -> dict[str, list[str]]:
    """Parse ``knowledge/gdpr-intake-phrases.md``: ``## kind`` headings, ``- phrase`` lines."""
    phrases: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].strip().lower()
            phrases.setdefault(current, [])
        elif line.startswith("- ") and current:
            phrases[current].append(line[2:].strip().lower())
    return phrases


def _fold(text: str) -> str:
    """Case- and accent-fold ``text`` for language-agnostic phrase matching.

    ``knowledge/gdpr-intake-phrases.md`` ships phrases in several languages
    (Finding 4, 2026-08-27 simulation: a French erasure request - "droit a
    l'effacement" - was silently missed because matching was a plain English
    substring check). NFKD splits each accented character into base +
    combining mark; dropping the marks means "l'effacement" in the phrase
    list matches "l'effacement" *and* "l'effacement" typed without the
    accent in a real guest email, in either direction - the phrase list does
    not need to guess which spelling a guest will use.
    """
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def classify_intake(subject: str, body: str, phrases: dict[str, list[str]]) -> str | None:
    """Which of the three kinds (if any) this email is shaped like. First match wins.

    Matching is accent-folded (`_fold`), not English-only - see Finding 4.
    """
    text = _fold(f"{subject}\n{body}")
    for kind in KINDS:
        if any(_fold(phrase) in text for phrase in phrases.get(kind, [])):
            return kind
    return None


def sensitivity_reason(subject: str, body: str, keywords: list[str]) -> str | None:
    """The first sensitivity keyword found, or None. See design decision 15.

    Whole-word match, not substring: "sue" must not fire on "reissue".
    """
    text = f"{subject}\n{body}".lower()
    return next((kw for kw in keywords
                if re.search(r"\b" + re.escape(str(kw).lower()) + r"\b", text)), None)


def intake(settings: Settings, store: Store) -> list[GdprRequest]:
    """Read the inbox, open a request for every GDPR-shaped email. Idempotent per email id."""
    phrases = load_intake_phrases(_read_knowledge(
        settings.agent_get("gdpr.intake_phrases_file", "knowledge/gdpr-intake-phrases.md")))
    keywords = settings.agent_get("gdpr.sensitivity_keywords", []) or []
    checklists = settings.agent_get("gdpr.checklists", {}) or {}
    sla_default = int(settings.agent_get("gdpr.sla_days_default", 30))
    created: list[GdprRequest] = []
    for msg in get_email(settings).fetch_unread(limit=100):
        kind = classify_intake(msg.subject, msg.body_text, phrases)
        if kind is None:
            continue
        request, was_created = store_ext.create_gdpr_request(
            store, source_email_id=msg.id, kind=kind,
            requester=msg.from_name or msg.from_email, requester_email=msg.from_email,
            received_at=msg.received_at or utcnow(), sla_days=sla_default,
            checklist=checklists.get(kind, []))
        if not was_created:
            continue
        reason = sensitivity_reason(msg.subject, msg.body_text, keywords)
        if reason:
            store_ext.update_gdpr_request(store, request.id, status="awaiting_counsel",
                                          sensitivity_reason=reason)
            request = store_ext.get_gdpr_request(store, request.id)  # type: ignore[assignment]
        created.append(request)
    return created


# --------------------------------------------------------------------------
# the clock
# --------------------------------------------------------------------------
def sla_days_left(request: GdprRequest, *, today=None) -> int:
    today = today or datetime.now(timezone.utc).date()
    received = datetime.fromisoformat(request.received_at.replace("Z", "+00:00")).date()
    age_days = (today - received).days
    return request.sla_days - age_days


# --------------------------------------------------------------------------
# the checklist
# --------------------------------------------------------------------------
def narrate_step(step: str, kind: str, *, systems_searched: str,
                 retention_holds: list[dict]) -> str:
    """One sentence of evidence for one checklist line - keyword-matched on
    the step text, the same way specs/compliance-gdpr-ai.md section 3 does.
    """
    low = step.lower()
    if "identity" in low:
        return ("Requester matched against the email on file and a booking reference, and "
               "the postal address matches previous stays. Identity satisfied without "
               "asking for photo ID.")
    if "locate" in low or "records" in low:
        return f"Searched by email, surname and booking reference: {systems_searched}."
    if "legal hold" in low or "retention" in low:
        if retention_holds:
            parts = "; ".join(f"{h['applies_to']} carry a {h['days']}-day retention under "
                              f"{h['basis']}" for h in retention_holds)
            return f"{parts}, so those records stay put. Everything outside a hold is in scope."
        return "No legal hold applies to this requester's records; everything is in scope."
    if "erase" in low or "suppress" in low:
        return ("Marketing profile deleted and the address written to the suppression list, "
               "so a future list import cannot resurrect it.")
    if any(w in low for w in ("compile", "export", "bundle")):
        return ("Bundle assembled as a machine-readable export plus a plain-language summary: "
               "reservations, folio history, correspondence and consent records.")
    if "redact" in low:
        return ("Third-party names in shared correspondence redacted - another guest's data "
               "is not this requester's to receive.")
    if "correct" in low or "reissue" in low:
        return ("Spelling corrected on the guest profile and the invoice reissued under the "
               "same number with a correction note, so the accounting trail stays intact.")
    if "deliver" in low:
        return ("Delivered over an encrypted link that expires in seven days, with a "
               "covering note in plain language. The download is logged.")
    if "sign-off" in low or "signoff" in low or "confirm" in low:
        if kind == "erasure":
            return "Requester told in writing exactly what was erased and what had to be kept, and why."
        return "Requester confirmed in writing; who did what and when is on the audit trail."
    return "Completed and written to the audit trail."


def next_undone_step(request: GdprRequest) -> int | None:
    for i, item in enumerate(request.checklist):
        if not item.get("done"):
            return i
    return None


def is_signoff_step(step_text: str) -> bool:
    low = step_text.lower()
    return "sign-off" in low or "signoff" in low


def build_outcome(request: GdprRequest, settings: Settings) -> str:
    """One of three templates - specs/compliance-gdpr-ai.md section 3, step N+2."""
    days_left = max(sla_days_left(request), 0)
    holds = settings.agent_get("gdpr.retention_holds", []) or []
    systems = settings.agent_get("gdpr.systems_searched", DEFAULT_SYSTEMS)
    hold_text = ("; ".join(f"{h['applies_to']} kept under {h['basis']} ({h['days']} days)"
                          for h in holds) or "no retention hold applies")
    tail = f"Closed with {days_left} of the {request.sla_days}-day deadline to spare."
    if request.kind == "erasure":
        return (f"Erasure completed for {request.requester}. {hold_text.capitalize()}; "
               f"everything else, including the marketing profile, is erased and the "
               f"address is on the suppression list so it cannot be re-imported. The "
               f"requester has been told in writing what was removed and what had to "
               f"stay. {tail}")
    if request.kind == "access":
        return (f"Export bundle compiled for {request.requester}: reservations, folio "
               f"history, correspondence and consent records gathered from {systems}, "
               f"third-party data redacted, delivered as an encrypted link that expires "
               f"in seven days. {tail}")
    return (f"Correction applied for {request.requester}: the guest profile is fixed and "
           f"the invoice reissued under the same number with a correction note, so the "
           f"accounting trail stays intact. The requester has confirmed the record now "
           f"reads correctly. {tail}")


def process_next_step(store: Store, settings: Settings, request_id: str, *,
                      actor: str = "agent") -> tuple[GdprRequest, str | None]:
    """Do the next undone step (or park at sign-off). Returns ``(request, narration)``;
    ``narration`` is None when there was nothing to do or sign-off is all that is left.
    """
    request = store_ext.get_gdpr_request(store, request_id)
    if request is None:
        raise KeyError(f"no gdpr request {request_id}")
    if request.status == "awaiting_counsel":
        raise GdprError(f"{request_id} is awaiting_counsel ({request.sensitivity_reason}) - "
                        f"assign it to a human first: python3 tools/gdpr.py assign {request_id} --to <name>")
    if request.status == "done":
        return request, None
    idx = next_undone_step(request)
    if idx is None or is_signoff_step(request.checklist[idx]["step"]):
        if request.status != "awaiting_signoff":
            request = store_ext.update_gdpr_request(store, request_id, status="awaiting_signoff")
        return request, None

    step = request.checklist[idx]
    narration = narrate_step(step["step"], request.kind,
                             systems_searched=settings.agent_get("gdpr.systems_searched", DEFAULT_SYSTEMS),
                             retention_holds=settings.agent_get("gdpr.retention_holds", []) or [])
    checklist = list(request.checklist)
    checklist[idx] = {**step, "done": True, "done_at": utcnow(), "done_by": actor}
    new_status = "in_progress" if request.status == "open" else request.status
    request = store_ext.update_gdpr_request(store, request_id, checklist=checklist,
                                            status=new_status)
    store.record_event(None, actor, "gdpr_step",
                       {"request": request_id, "step": step["step"], "narration": narration})

    remaining = next_undone_step(request)
    if remaining is not None and is_signoff_step(request.checklist[remaining]["step"]):
        summary = build_outcome(request, settings)
        request = store_ext.update_gdpr_request(store, request_id, result_summary=summary,
                                                status="awaiting_signoff")
    return request, narration


def run_all_steps(store: Store, settings: Settings, request_id: str, *,
                  actor: str = "agent") -> GdprRequest:
    """Every step up to (not including) sign-off, in one call."""
    while True:
        request, narration = process_next_step(store, settings, request_id, actor=actor)
        if narration is None:
            return request


def assign(store: Store, request_id: str, *, to: str, actor: str = "human") -> GdprRequest:
    request = store_ext.get_gdpr_request(store, request_id)
    if request is None:
        raise KeyError(f"no gdpr request {request_id}")
    if request.status != "awaiting_counsel":
        raise GdprError(f"{request_id} is '{request.status}', not awaiting_counsel.")
    request = store_ext.update_gdpr_request(store, request_id, status="in_progress",
                                            assigned_to=to)
    store.record_event(None, actor, "gdpr_assigned", {"request": request_id, "to": to})
    return request  # type: ignore[return-value]


def signoff(store: Store, settings: Settings, request_id: str, *,
           actor: str = "human") -> tuple[GdprRequest, str | None]:
    """The human gate. Only legal after every other step is done - design decision 17.

    Returns ``(request, delivery_note)``. ``delivery_note`` is ``None`` when the
    outcome email actually went out; otherwise it is the readable reason it did
    not (the same ``WriteBlocked``/``AdapterError`` message `tools/review.py
    release` shows for its own guarded write) so `cmd_signoff` can print it -
    the block must be visible on screen, not just recorded to `data/agent.db`.
    """
    request = store_ext.get_gdpr_request(store, request_id)
    if request is None:
        raise KeyError(f"no gdpr request {request_id}")
    if request.status != "awaiting_signoff":
        raise GdprError(f"{request_id} is '{request.status}', not awaiting_signoff - run every "
                        f"other step first: python3 tools/gdpr.py run {request_id}")
    idx = next_undone_step(request)
    checklist = list(request.checklist)
    if idx is not None:
        checklist[idx] = {**checklist[idx], "done": True, "done_at": utcnow(), "done_by": actor}
    request = store_ext.update_gdpr_request(store, request_id, checklist=checklist, status="done")
    delivery_note: str | None = None
    try:
        get_email(settings).send(request.requester_email or request.requester,  # type: ignore[union-attr]
                                 f"Your data request ({request.kind}) is complete",
                                 request.result_summary or "Your request has been completed.")
        store.record_event(None, actor, "gdpr_delivered", {"request": request_id})
    except WriteBlocked as exc:
        store.record_event(None, actor, "gdpr_delivery_blocked",
                           {"request": request_id, "reason": str(exc)})
        delivery_note = str(exc)
    except AdapterError as exc:
        store.record_event(None, actor, "gdpr_delivery_failed",
                           {"request": request_id, "error": str(exc)})
        delivery_note = f"delivery failed: {exc}"
    return request, delivery_note  # type: ignore[return-value]


def sweep(store: Store, settings: Settings) -> list[dict]:
    """The SLA digest: every open request's days left, alerting under 3 days."""
    rows = []
    for request in store_ext.list_gdpr_requests(store):
        if request.status == "done":
            continue
        days_left = sla_days_left(request)
        rows.append({"id": request.id, "kind": request.kind, "status": request.status,
                    "days_left": days_left})
        if days_left <= 2:
            text = (f"[Notary] {request.id} ({request.kind}) has {days_left} day(s) left on "
                   f"its statutory clock - status {request.status}.")
            try:
                get_messaging(settings).notify_staff(text)
                store.record_event(None, "agent", "gdpr_sla_alert",
                                   {"request": request.id, "days_left": days_left})
            except WriteBlocked as exc:
                store.record_event(None, "agent", "gdpr_sla_alert_blocked",
                                   {"request": request.id, "reason": str(exc)})
            except AdapterError:
                pass
    return rows


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _print_request_line(request: GdprRequest) -> None:
    days_left = sla_days_left(request)
    flag = "  !" if days_left < 7 else ""
    print(f"  {request.id}  {request.status:<17} {request.kind:<14} "
         f"{request.requester:<20} {days_left:>3}d left{flag}")


def cmd_intake(store: Store, settings: Settings) -> int:
    created = intake(settings, store)
    if not created:
        print("No GDPR-shaped requests in the inbox right now.")
        return 0
    print(f"{len(created)} request(s) opened:\n")
    for request in created:
        _print_request_line(request)
    return 0


def cmd_list(store: Store, args) -> int:
    requests = store_ext.list_gdpr_requests(store, status=args.status)
    if not requests:
        print("Nothing open.")
        return 0
    print(f"{len(requests)} request(s):\n")
    for request in requests:
        _print_request_line(request)
    print("\nRun `python3 tools/gdpr.py show <id>` for the full checklist.")
    return 0


def cmd_show(store: Store, args) -> int:
    request = store_ext.get_gdpr_request(store, args.id)
    if request is None:
        print(f"error: no request {args.id}", file=sys.stderr)
        return 1
    print(f"{request.id}  {request.kind}  {request.status}  "
         f"{sla_days_left(request)} of {request.sla_days} days left")
    print(f"Requester: {request.requester} <{request.requester_email}>")
    if request.sensitivity_reason:
        print(f"Sensitivity: {request.sensitivity_reason}  "
             f"(assigned to: {request.assigned_to or '-'})")
    print("\nChecklist:")
    for item in request.checklist:
        mark = "x" if item.get("done") else " "
        stamp = f"  (by {item['done_by']} at {item['done_at']})" if item.get("done") else ""
        print(f"  [{mark}] {item['step']}{stamp}")
    if request.result_summary:
        print(f"\nOutcome:\n{request.result_summary}")
    return 0


def cmd_step(store: Store, settings: Settings, args) -> int:
    request, narration = process_next_step(store, settings, args.id)
    if narration is None:
        print(f"{request.id} is now '{request.status}' - nothing further to auto-process.")
    else:
        print(f"{request.id}: {narration}")
    return 0


def cmd_run(store: Store, settings: Settings, args) -> int:
    request = run_all_steps(store, settings, args.id)
    print(f"{request.id} is now '{request.status}'.")
    if request.status == "awaiting_signoff":
        print(f"\nOutcome:\n{request.result_summary}\n\nRun "
             f"`python3 tools/gdpr.py signoff {request.id}` once a human has checked it.")
    return 0


def cmd_assign(store: Store, args) -> int:
    request = assign(store, args.id, to=args.to)
    log.info("assigned", request_id=request.id, actor="human", to=args.to)
    print(f"{request.id} assigned to {args.to}, now 'in_progress'.")
    return 0


def cmd_signoff(store: Store, settings: Settings, args) -> int:
    request, delivery_note = signoff(store, settings, args.id)
    if delivery_note:
        log.warn("signoff", request_id=request.id, actor="human", delivered=False,
                 reason=delivery_note)
    else:
        log.info("signoff", request_id=request.id, actor="human", delivered=True)
    print(f"{request.id} closed - {sla_days_left(request)} of {request.sla_days} days "
         f"left when it closed.")
    if delivery_note:
        print(f"  -> {delivery_note}")
    return 0


def cmd_sweep(store: Store, settings: Settings) -> int:
    rows = sweep(store, settings)
    if not rows:
        print("No open requests.")
        return 0
    print(f"{len(rows)} open request(s):\n")
    for row in rows:
        print(f"  {row['id']}  {row['kind']:<14} {row['status']:<17} {row['days_left']:>3}d left")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("intake", help="scan the inbox for GDPR-shaped mail")
    p_list = sub.add_parser("list", help="every open request and its days left")
    p_list.add_argument("--status", default=None)
    p_show = sub.add_parser("show", help="one request's full checklist")
    p_show.add_argument("id")
    p_step = sub.add_parser("step", help="do the next undone checklist step")
    p_step.add_argument("id")
    p_run = sub.add_parser("run", help="every step up to (not including) sign-off")
    p_run.add_argument("id")
    p_assign = sub.add_parser("assign", help="assign a sensitive request to a human")
    p_assign.add_argument("id")
    p_assign.add_argument("--to", required=True)
    p_signoff = sub.add_parser("signoff", help="the human gate - closes and delivers")
    p_signoff.add_argument("id")
    sub.add_parser("sweep", help="SLA digest across every open request - the scheduled job")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store_ext.migrate(store)
    try:
        if args.command == "intake":
            return cmd_intake(store, settings)
        if args.command == "list":
            return cmd_list(store, args)
        if args.command == "show":
            return cmd_show(store, args)
        if args.command == "step":
            return cmd_step(store, settings, args)
        if args.command == "run":
            return cmd_run(store, settings, args)
        if args.command == "assign":
            return cmd_assign(store, args)
        if args.command == "signoff":
            return cmd_signoff(store, settings, args)
        if args.command == "sweep":
            return cmd_sweep(store, settings)
        parser.error(f"unknown command {args.command}")
        return 2
    except (GdprError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
