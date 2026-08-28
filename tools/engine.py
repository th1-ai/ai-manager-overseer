"""tools/engine.py - the Warden's screening logic: one deterministic verdict
per draft another agent produced.

Five checks, always in this order, no model call anywhere (see
docs/how-it-works.md "Deciding a verdict"):

    1. category block     (rule: category-blocks)   -> escalated
    2. allergen/safety     (rule: allergen-check)     -> escalated
    3. rate cross-check    (rule: rate-crosscheck)    -> blocked or held_rule
    4. confidence gate     (rule: confidence-gate)    -> blocked
    5. tone check          (rule: tone-check)         -> held_rule

`screen_draft()` is a pure function over a settings object and a plain dict -
no I/O, easy to test. `process_draft()` is the glue `tools/run.py` and
`tools/demo.py` share: it upserts the item, runs `screen_draft()`, records
the verdict, and (on blocked/escalated) notifies the duty manager through
the messaging adapter - a guarded write, so shadow mode blocks it exactly
like every other repo in this family.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.adapters import get_messaging, get_pms
from core.adapters.base import AdapterError
from core.config import Settings, repo_root
from core.review import WriteBlocked
from core.store import Item, Store

RULE_LABELS = {
    "confidence-gate": "the confidence gate",
    "rate-crosscheck": "the rate cross-check",
    "category-blocks": "human-only categories",
    "allergen-check": "the allergen check",
    "tone-check": "the tone check",
}


@dataclass
class Verdict:
    """The Warden's decision on one draft, with the evidence that produced it."""

    verdict: str  # passed | blocked | held_rule | escalated
    blocked_by: list[str] = field(default_factory=list)
    held_by: list[str] = field(default_factory=list)
    escalated_by: list[str] = field(default_factory=list)
    detail: str = ""
    evidence: dict = field(default_factory=dict)

    def fired(self) -> list[str]:
        return [*self.escalated_by, *self.blocked_by, *self.held_by]


def load_drafts(settings: Settings, *, limit: int = 100) -> list[dict]:
    """Read pending drafts from the configured feed (config/agent.yaml:
    draft_feed). ``mock`` (the default) reads the bundled fixtures, so
    `make demo` and the tests never need a real drop folder; ``dir`` reads
    ``draft_feed.dir`` (default ``data/imports/drafts``) - the recipe for
    wiring up a real one is in docs/integrations.md#implement-your-own.

    Fixtures live in ``fixtures/inbound/drafts/``, a level below the guest
    emails in ``fixtures/inbound/`` itself, so the Notary's email adapter
    (which globs every ``*.json`` directly in ``fixtures/inbound/``) never
    mistakes a draft for a guest message.
    """
    cfg = settings.agent_get("draft_feed", {}) or {}
    if cfg.get("adapter") == "dir":
        directory = Path(cfg.get("dir") or "data/imports/drafts")
        if not directory.is_absolute():
            directory = repo_root() / directory
    else:
        directory = repo_root() / "fixtures" / "inbound" / "drafts"
    if not directory.exists():
        return []
    drafts: list[dict] = []
    for path in sorted(directory.glob("draft-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("id"):
            drafts.append(data)
        if len(drafts) >= limit:
            break
    return drafts


def _read_knowledge(filename: str) -> str:
    """``knowledge/<filename>``, falling back to the shipped ``.example.md``."""
    base = repo_root() / "knowledge"
    path = base / filename
    if not path.exists():
        stem = filename.rsplit(".", 1)[0]
        path = base / f"{stem}.example.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _allergen_confirmed(claim: str, kb_text: str) -> bool:
    """A claim is confirmed when it matches a knowledge-base line closely -
    either contains it or is contained by it, case-insensitive. Anything
    else is treated as unverified, on purpose: silence is not confirmation.
    """
    needle = claim.strip().lower()
    for raw in kb_text.splitlines():
        line = raw.strip("- ").strip().lower()
        if line and (needle in line or line in needle):
            return True
    return False


def check_category_block(draft: dict, cfg: dict) -> list[str]:
    if not cfg.get("enabled", True):
        return []
    categories = {str(c) for c in (cfg.get("categories") or [])}
    return ["category-blocks"] if draft.get("category") in categories else []


def _word_hit(text: str, keywords: list[str]) -> bool:
    """Whole-word, case-insensitive match - "sue" must not fire on "reissue"."""
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in keywords)


def check_allergen(draft: dict, cfg: dict) -> tuple[list[str], list[str]]:
    """Returns ``(fired_rules, unverified_claims)``."""
    if not cfg.get("enabled", True):
        return [], []
    keywords = [str(k).lower() for k in (cfg.get("keywords") or [])]
    kb = _read_knowledge("allergens.md")
    unverified = [claim for claim in (draft.get("claims") or [])
                 if _word_hit(str(claim).lower(), keywords)
                 and not _allergen_confirmed(str(claim), kb)]
    return (["allergen-check"] if unverified else []), unverified


def get_pms_rate(settings: Settings, room_type_id: str, check_in: str) -> float | None:
    try:
        rows = get_pms(settings).get_rates(check_in, check_in, room_type=room_type_id)
    except AdapterError:
        return None
    return rows[0].price if rows else None


def check_rate(draft: dict, settings: Settings, cfg: dict) -> dict:
    """Rate cross-check. Returns ``{}`` when the draft has nothing to check."""
    price, room_type_id, check_in = (draft.get("quoted_price"), draft.get("room_type_id"),
                                     draft.get("check_in"))
    if price is None or not room_type_id or not check_in:
        return {}
    pms_rate = get_pms_rate(settings, room_type_id, check_in)
    if not pms_rate:
        return {}
    gap = round(pms_rate - float(price), 2)
    gap_pct = round(gap / pms_rate * 100)
    severity = None
    if gap_pct >= cfg.get("rate_block_threshold_pct", 15):
        severity = "blocked"
    elif gap_pct >= cfg.get("rate_held_threshold_pct", 5):
        severity = "held"
    return {"gap": gap, "gap_pct": gap_pct, "pms_rate": pms_rate,
           "quoted_price": float(price), "severity": severity}


def check_confidence(draft: dict, threshold: float) -> bool:
    confidence = draft.get("confidence")
    return confidence is not None and float(confidence) < float(threshold)


def check_tone(draft: dict, cfg: dict) -> list[str]:
    if not cfg.get("enabled", True):
        return []
    text = str(draft.get("draft_text") or "")
    phrases = [str(p).lower() for p in (cfg.get("forbidden_phrases") or [])]
    hit = any(p in text.lower() for p in phrases)
    letters = [c for c in text if c.isalpha()]
    shouting = bool(letters) and sum(1 for c in letters if c.isupper()) / len(letters) > 0.3
    return ["tone-check"] if (hit or shouting) else []


def _narrate(verdict: str, draft: dict, blocked_by: list[str], held_by: list[str],
            escalated_by: list[str], rate: dict, unverified: list[str]) -> str:
    def labels(keys: list[str]) -> str:
        return " + ".join(RULE_LABELS[k] for k in keys)

    bits = []
    if rate:
        bits.append(f"quoted {rate['quoted_price']:g} against a PMS rate of "
                   f"{rate['pms_rate']:g} ({rate['gap_pct']}% gap)")
    if draft.get("confidence") is not None:
        bits.append(f"{draft['confidence']:g}% confidence")
    evidence = "; ".join(bits) or "no price or confidence evidence on this draft"

    if verdict == "escalated":
        reasons = []
        if "category-blocks" in escalated_by:
            reasons.append(f"category '{draft.get('category')}' is human-only")
        if "allergen-check" in escalated_by:
            reasons.append("an unverified claim: " + "; ".join(unverified))
        return (f"Escalated by {labels(escalated_by)} — {'; '.join(reasons)}. Sent straight "
               f"to a human; no AI answer goes to the guest on this one.")
    if verdict == "blocked":
        return f"Blocked by {labels(blocked_by)} — {evidence}. Held for a duty manager; the guest was told nothing."
    if verdict == "held_rule":
        return f"Held by {labels(held_by)} — {evidence}. Parked for review; nothing has gone to the guest yet."
    return f"Passed — {evidence}."


def screen_draft(settings: Settings, draft: dict) -> Verdict:
    """The whole Warden decision for one draft. Pure function, no I/O."""
    cat_cfg = settings.agent_get("category_blocks", {}) or {}
    allergen_cfg = settings.agent_get("allergen_check", {}) or {}
    tone_cfg = settings.agent_get("tone_check", {}) or {}
    confidence_threshold = settings.agent_get("confidence_threshold", 80)
    rate_cfg = {"rate_block_threshold_pct": settings.agent_get("rate_block_threshold_pct", 15),
               "rate_held_threshold_pct": settings.agent_get("rate_held_threshold_pct", 5)}

    escalated_by = check_category_block(draft, cat_cfg)
    allergen_rules, unverified = check_allergen(draft, allergen_cfg)
    escalated_by += allergen_rules

    rate_result = check_rate(draft, settings, rate_cfg)
    blocked_by, held_by = [], []
    if rate_result.get("severity") == "blocked":
        blocked_by.append("rate-crosscheck")
    elif rate_result.get("severity") == "held":
        held_by.append("rate-crosscheck")
    if check_confidence(draft, confidence_threshold):
        blocked_by.append("confidence-gate")
    held_by += check_tone(draft, tone_cfg)

    if escalated_by:
        verdict = "escalated"
    elif blocked_by:
        verdict = "blocked"
    elif held_by:
        verdict = "held_rule"
    else:
        verdict = "passed"

    detail = _narrate(verdict, draft, blocked_by, held_by, escalated_by, rate_result, unverified)
    return Verdict(verdict=verdict, blocked_by=blocked_by, held_by=held_by,
                  escalated_by=escalated_by, detail=detail,
                  evidence={"rate": rate_result, "unverified_claims": unverified})


def process_draft(settings: Settings, store: Store, draft: dict) -> tuple[Item, bool]:
    """Screen one draft and queue the result. Idempotent - see docs/how-it-works.md."""
    item = store.upsert_item("draft_feed", str(draft["id"]), kind="draft", payload=draft)
    if item.intent and item.draft is not None:
        return item, False

    result = screen_draft(settings, draft)
    store.set_fields(item.id, intent=result.verdict,
                     confidence=float(draft.get("confidence") or 0.0),
                     draft={"verdict": result.verdict, "blocked_by": result.blocked_by,
                            "held_by": result.held_by, "escalated_by": result.escalated_by,
                            "detail": result.detail, "evidence": result.evidence})

    if result.verdict == "passed":
        item = store.transition(item.id, "dispatched", actor="agent", detail={"verdict": "passed"})
        item = store.transition(item.id, "auto_sent", actor="agent", detail={"detail": result.detail})
    else:
        item = store.transition(item.id, "needs_human", actor="agent",
                                detail={"verdict": result.verdict, "fired": result.fired()})
        if result.verdict in ("blocked", "escalated"):
            _notify_duty_manager(settings, store, item, draft, result)
    return item, True


def _notify_duty_manager(settings: Settings, store: Store, item: Item, draft: dict,
                         result: Verdict) -> None:
    text = (f"[Warden] {result.verdict} — {draft.get('agent', 'an agent')}'s draft to "
           f"{draft.get('guest', 'a guest')} on {draft.get('channel', 'a channel')}: "
           f"{result.detail}")
    try:
        get_messaging(settings).notify_staff(text, item=item)
        store.record_event(item.id, "agent", "duty_manager_notified", {"text": text})
    except WriteBlocked as exc:
        store.record_event(item.id, "agent", "notify_blocked", {"reason": str(exc)})
    except AdapterError as exc:
        store.record_event(item.id, "agent", "notify_failed", {"error": str(exc)})
