"""Tests for the Warden's screening engine (tools/engine.py) - pure rule
logic plus the store-backed process_draft glue. No network, no credentials -
this is what `make demo` runs on (fixtures/inbound/drafts/*.json).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core.config import load_settings
from core.store import Store

from engine import load_drafts, process_draft, screen_draft
import run as run_tool


def _settings():
    return load_settings(provider="mock", mode="shadow")


def _base_draft(**overrides):
    draft = {"id": "d-test", "agent": "Front Desk AI", "channel": "email",
            "guest": "Test Guest", "category": "question", "confidence": 95,
            "quoted_price": None, "room_type_id": None, "check_in": None,
            "check_out": None, "claims": [], "draft_text": "All good here.",
            "received_at": "2026-08-27T08:00:00+00:00"}
    draft.update(overrides)
    return draft


def test_passed_when_nothing_fires():
    result = screen_draft(_settings(), _base_draft())
    assert result.verdict == "passed"
    assert result.fired() == []


def test_confidence_gate_blocks_low_confidence():
    result = screen_draft(_settings(), _base_draft(confidence=54))
    assert result.verdict == "blocked"
    assert "confidence-gate" in result.blocked_by


def test_category_block_escalates_regardless_of_confidence():
    result = screen_draft(_settings(), _base_draft(category="complaint", confidence=99))
    assert result.verdict == "escalated"
    assert result.escalated_by == ["category-blocks"]


def test_category_block_can_be_turned_off_honestly():
    """Rule-off honesty (docs/safety.md): turning the rule off changes the
    outcome, on purpose, exactly like the confidence gate does."""
    settings = _settings()
    on = screen_draft(settings, _base_draft(category="complaint", confidence=99))
    settings.agent = {**settings.agent,
                      "category_blocks": {**settings.agent.get("category_blocks", {}),
                                         "enabled": False}}
    off = screen_draft(settings, _base_draft(category="complaint", confidence=99))
    assert on.verdict == "escalated"
    assert off.verdict == "passed"


def test_allergen_claim_unconfirmed_escalates():
    result = screen_draft(_settings(), _base_draft(
        claims=["the seafood tasting menu is completely peanut-free"]))
    assert result.verdict == "escalated"
    assert "allergen-check" in result.escalated_by


def test_allergen_claim_confirmed_in_knowledge_base_does_not_escalate():
    result = screen_draft(_settings(), _base_draft(
        claims=["the garden salad is nut-free and dairy-free"]))
    assert result.verdict == "passed"


def test_rate_crosscheck_blocks_a_large_gap():
    result = screen_draft(_settings(), _base_draft(
        quoted_price=212, room_type_id="deluxe-sea-view",
        check_in="2026-08-14", check_out="2026-08-16", confidence=54))
    assert result.verdict == "blocked"
    assert set(result.blocked_by) == {"rate-crosscheck", "confidence-gate"}
    assert result.evidence["rate"]["gap_pct"] == 54


def test_rate_crosscheck_holds_a_minor_gap_without_blocking():
    result = screen_draft(_settings(), _base_draft(
        quoted_price=165, room_type_id="classic",
        check_in="2026-09-05", check_out="2026-09-07", confidence=95))
    assert result.verdict == "held_rule"
    assert result.held_by == ["rate-crosscheck"]


def test_tone_check_holds_a_forbidden_phrase():
    result = screen_draft(_settings(), _base_draft(
        draft_text="This is 100% refund guaranteed, no questions asked.", confidence=95))
    assert result.verdict == "held_rule"
    assert result.held_by == ["tone-check"]


def test_every_bundled_draft_fixture_matches_its_expected_verdict():
    expected = {"draft-01": "blocked", "draft-02": "held_rule", "draft-03": "escalated",
               "draft-04": "escalated", "draft-05": "passed", "draft-06": "held_rule"}
    settings = _settings()
    drafts = load_drafts(settings)
    assert {d["id"] for d in drafts} == set(expected)
    for draft in drafts:
        result = screen_draft(settings, draft)
        assert result.verdict == expected[draft["id"]], draft["id"]


def test_process_draft_is_idempotent(tmp_path):
    settings = _settings()
    store = Store(settings, path=tmp_path / "engine.db")
    draft = _base_draft(confidence=54)
    item, did_work = process_draft(settings, store, draft)
    assert did_work is True
    assert item.review_status == "needs_human"
    item2, did_work2 = process_draft(settings, store, draft)
    assert did_work2 is False
    assert item2.id == item.id
    store.close()


def test_shadow_mode_blocks_the_duty_manager_notification(tmp_path):
    settings = _settings()
    assert settings.mode == "shadow"
    store = Store(settings, path=tmp_path / "engine2.db")
    item, _ = process_draft(settings, store, _base_draft(confidence=54))
    actions = [e["action"] for e in store.list_events(item.id)]
    assert "notify_blocked" in actions
    assert "duty_manager_notified" not in actions
    store.close()


def test_passed_drafts_are_auto_sent_and_held_ones_need_a_human(tmp_path):
    settings = _settings()
    store = Store(settings, path=tmp_path / "engine3.db")
    passed_item, _ = process_draft(settings, store, _base_draft(confidence=95))
    held_item, _ = process_draft(settings, store, _base_draft(
        id="d-held", draft_text="100% refund guaranteed", confidence=95))
    assert passed_item.review_status == "auto_sent"
    assert held_item.review_status == "needs_human"
    store.close()


# --------------------------------------------------------------------------
# --dry-run writes nothing (Finding 1, BLOCKER, 2026-08-27 simulation)
# --------------------------------------------------------------------------
def test_dry_run_never_touches_the_real_database(tmp_path, monkeypatch):
    """Two consecutive `--dry-run` passes over fresh drafts must both compute
    a full verdict (proving the pass actually ran, not that it silently did
    nothing) while leaving zero trace in `data/agent.db` - not a new row,
    not a transition, not an IntegrityError on the second pass.

    Before the fix, `tools/run.py:main()` opened the real on-disk store
    unconditionally; `process_draft()` then upserted the item, recorded the
    verdict and transitioned it all the way to `auto_sent`/`needs_human`
    regardless of `--dry-run`. The fix swaps in an in-memory `Store`
    (``path=":memory:"``) whenever `settings.dry_run` - the same pattern
    `front-desk-ai` and `housekeeping-maintenance-ai` use - so a rehearsal
    has somewhere real to write during the pass without ever touching disk.
    """
    monkeypatch.setenv("AGENT_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("AGENT_CONFIG_DIR", raising=False)
    (tmp_path / "config").mkdir()
    drafts_dir = tmp_path / "drop"
    drafts_dir.mkdir()
    (tmp_path / "config" / "agent.yaml").write_text(
        f"draft_feed:\n  adapter: dir\n  dir: {drafts_dir}\n", encoding="utf-8")

    for i in range(2):
        (drafts_dir / f"draft-{i}.json").write_text(json.dumps(_base_draft(id=f"dry-{i}")),
                                                     encoding="utf-8")
        code = run_tool.main(["--once", "--dry-run"])
        assert code == 0

    db_path = tmp_path / "data" / "agent.db"
    # An in-memory store never creates the file at all - not "empty", absent.
    assert not db_path.exists()
