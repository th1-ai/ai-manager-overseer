"""Tests for the daily governance note (tools/digest.py) - the one LLM call
in this repo, always exercised with provider=mock here.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core.config import load_settings
from core.store import Store

import store_ext
from digest import build_summary, run_digest
from engine import process_draft


def _settings():
    return load_settings(provider="mock", mode="shadow")


def test_governance_note_comes_back_from_the_mock_fixture(tmp_path):
    settings = _settings()
    store = Store(settings, path=tmp_path / "digest.db")
    store_ext.migrate(store)
    note = run_digest(settings, store, provider="mock")
    assert note
    assert "Certainly" not in note and "Here is" not in note
    store.close()


def test_build_summary_counts_verdicts(tmp_path):
    settings = _settings()
    store = Store(settings, path=tmp_path / "digest2.db")
    store_ext.migrate(store)
    process_draft(settings, store, {
        "id": "d1", "agent": "Front Desk AI", "channel": "email", "guest": "G",
        "category": "question", "confidence": 95, "quoted_price": None,
        "room_type_id": None, "check_in": None, "check_out": None, "claims": [],
        "draft_text": "hi", "received_at": "2026-08-27T08:00:00+00:00"})
    summary = build_summary(store)
    assert summary["screened"] == 1
    assert summary["passed"] == 1
    store.close()
