"""Tests for the Warden-specific review-queue actions: release, reject, the
go-live `stale` step, and pause/resume (tools/review.py, tools/store_ext.py).
No network, no credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core.adapters import get_messaging
from core.config import load_settings
from core.review import WriteBlocked, reject, stale_backlog
from core.store import Store

import review
import store_ext
from engine import process_draft


def _settings():
    return load_settings(provider="mock", mode="shadow")


def _store(tmp_path, name="review.db"):
    settings = _settings()
    store = Store(settings, path=tmp_path / name)
    store_ext.migrate(store)
    return settings, store


def _blocked_item(settings, store):
    draft = {"id": "d-review", "agent": "Front Desk AI", "channel": "email",
            "guest": "Test Guest", "category": "question", "confidence": 40,
            "quoted_price": None, "room_type_id": None, "check_in": None,
            "check_out": None, "claims": [], "draft_text": "hello",
            "received_at": "2026-08-27T08:00:00+00:00"}
    item, _ = process_draft(settings, store, draft)
    return item


def test_release_records_the_decision_even_though_shadow_blocks_the_notify(tmp_path):
    settings, store = _store(tmp_path)
    item = _blocked_item(settings, store)
    approved = store.transition(item.id, "approved", "human", {"note": "checked, fine to send"})
    assert approved.review_status == "approved"
    try:
        get_messaging(settings).notify_staff("released", item=approved)
        notified = True
    except WriteBlocked:
        notified = False
    assert notified is False  # shadow blocks the write; the approval above still stands
    store.close()


def test_reject_leaves_the_hold_standing(tmp_path):
    settings, store = _store(tmp_path)
    item = _blocked_item(settings, store)
    rejected = reject(store, item.id, reason="not right")
    assert rejected.review_status == "rejected"
    store.close()


def test_pause_and_resume_agent_round_trip(tmp_path):
    settings, store = _store(tmp_path)
    paused = store_ext.pause_agent(store, "Front Desk AI", actor="human", reason="testing")
    assert paused["status"] == "paused"
    assert paused["paused_by"] == "human"
    resumed = store_ext.resume_agent(store, "Front Desk AI", actor="human")
    assert resumed["status"] == "active"
    rows = store_ext.list_fleet(store)
    assert any(r["agent_name"] == "Front Desk AI" for r in rows)
    store.close()


def test_stale_backlog_clears_un_released_holds_at_go_live(tmp_path):
    settings, store = _store(tmp_path)
    item = _blocked_item(settings, store)
    moved = stale_backlog(store)
    assert item.id in moved
    refreshed = store.get_item(item.id)
    assert refreshed.review_status == "stale"
    store.close()


def test_sample_item_shows_marker_in_list_line_and_show(tmp_path, capsys):
    """core/store.py tags an item read through a mock adapter outside `make
    demo` as `_sample` (`Item.is_sample`) - a human working the real queue
    must see that at a glance, in both `list` and `show`."""
    settings, store = _store(tmp_path)
    item = store.upsert_item("draft_feed", "sample-marker-1", kind="draft",
                             payload={"agent": "Front Desk AI", "guest": "Test Guest",
                                      "_sample": True})
    assert item.is_sample

    capsys.readouterr()
    review._print_item_line(item)
    assert "[SAMPLE DATA]" in capsys.readouterr().out

    rc = review.cmd_show(store, SimpleNamespace(id=item.id))
    assert rc == 0
    assert "[SAMPLE DATA]" in capsys.readouterr().out
    store.close()
