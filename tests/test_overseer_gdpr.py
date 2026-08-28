"""Tests for the Notary's request desk (tools/gdpr.py). No network, no
credentials - the whole flow is deterministic (specs/compliance-gdpr-ai.md
section 7).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest

from core.config import load_settings
from core.store import Store

import store_ext
from gdpr import (GdprError, assign, classify_intake, intake, load_intake_phrases,
                  process_next_step, run_all_steps, sensitivity_reason, signoff,
                  sla_days_left)


def _settings():
    return load_settings(provider="mock", mode="shadow")


def _store(tmp_path):
    settings = _settings()
    store = Store(settings, path=tmp_path / "gdpr.db")
    store_ext.migrate(store)
    return settings, store


PHRASES = load_intake_phrases((REPO_ROOT / "knowledge" / "gdpr-intake-phrases.example.md")
                              .read_text(encoding="utf-8"))


def test_classify_intake_recognises_all_three_kinds():
    assert classify_intake("", "please delete my personal data", PHRASES) == "erasure"
    assert classify_intake("", "send me a copy of all data you hold", PHRASES) == "access"
    assert classify_intake("", "my name is misspelled, please correct my details", PHRASES) == "rectification"


def test_classify_intake_returns_none_for_an_ordinary_email():
    assert classify_intake("Check-in time", "What time can we check in?", PHRASES) is None


def test_classify_intake_catches_non_english_requests():
    """Finding 4 (2026-08-27 simulation): a French erasure request was
    silently missed because matching was an English-only substring check.
    This is the exact sim repro, plus one each in es/de/it/pt."""
    french = ("Demande RGPD", "Je souhaite exercer mon droit à l'effacement... "
             "supprimer mes données personnelles.")
    assert classify_intake(*french, PHRASES) == "erasure"
    assert classify_intake("", "Quiero eliminar mis datos personales, por favor.", PHRASES) == "erasure"
    assert classify_intake(
        "", "Ich möchte, dass Sie meine personenbezogenen Daten löschen.", PHRASES) == "erasure"
    assert classify_intake("", "Vorrei una copia dei miei dati, per favore.", PHRASES) == "access"
    assert classify_intake("", "Por favor corrigir os meus dados de contacto.", PHRASES) == "rectification"


def test_classify_intake_folds_accents_in_either_direction():
    """`_fold()` strips diacritics from both the phrase list and the email,
    so an accented phrase still matches unaccented guest text, and an
    unaccented phrase (as the shipped list uses) still matches accented
    guest text - either side may or may not have typed the accent."""
    phrases = {"erasure": ["droit à l'effacement"], "access": [], "rectification": []}
    assert classify_intake("", "mon droit a l'effacement, merci", phrases) == "erasure"
    assert classify_intake("", "mon droit à l'effacement, merci", phrases) == "erasure"


def test_sensitivity_reason_is_whole_word_not_substring():
    """Regression: "sue" must not fire on "reissue" - see docs/how-it-works.md."""
    keywords = ["sue", "lawsuit", "journalist"]
    assert sensitivity_reason("", "please reissue my invoice", keywords) is None
    assert sensitivity_reason("", "my lawyer will sue you", keywords) == "sue"


def test_sla_days_left_matches_the_canonical_example():
    request = store_ext.GdprRequest(id="gr-x", source_email_id=None, kind="erasure",
                                    requester="M. Halvorsen", requester_email="",
                                    received_at="2026-08-05T09:00:00+00:00", sla_days=30,
                                    status="open", checklist=[])
    assert sla_days_left(request, today=date(2026, 8, 27)) == 8


def test_intake_opens_one_request_per_email_and_skips_non_gdpr_mail(tmp_path):
    settings, store = _store(tmp_path)
    created = intake(settings, store)
    assert {r.kind for r in created} == {"erasure", "access", "rectification"}
    assert len(created) == 4  # 3 clean + 1 sensitive erasure (email-06)
    again = intake(settings, store)
    assert again == []  # idempotent: nothing new on a second pass
    store.close()


def test_sensitive_request_is_routed_to_awaiting_counsel_not_auto_processed(tmp_path):
    settings, store = _store(tmp_path)
    intake(settings, store)
    sensitive = next(r for r in store_ext.list_gdpr_requests(store) if r.kind == "erasure"
                     and r.sensitivity_reason)
    assert sensitive.status == "awaiting_counsel"
    with pytest.raises(GdprError):
        process_next_step(store, settings, sensitive.id)
    assigned = assign(store, sensitive.id, to="counsel")
    assert assigned.status == "in_progress"
    store.close()


def test_checklist_runs_to_awaiting_signoff_then_signoff_closes_it(tmp_path):
    settings, store = _store(tmp_path)
    created = intake(settings, store)
    erasure = next(r for r in created if r.kind == "erasure" and not r.sensitivity_reason)
    request = run_all_steps(store, settings, erasure.id)
    assert request.status == "awaiting_signoff"
    assert all(item["done"] for item in request.checklist[:-1])
    assert request.checklist[-1]["done"] is False  # the sign-off step itself
    assert "Closed with" in request.result_summary
    closed, delivery_note = signoff(store, settings, erasure.id)
    assert closed.status == "done"
    assert all(item["done"] for item in closed.checklist)
    # shadow mode (the test config's default) blocks the outcome email - the
    # block must come back to the caller, not just land silently in the store
    # (Finding 2: `cmd_signoff` prints this as a `-> ...` line, same as
    # `tools/review.py release`).
    assert delivery_note is not None and "shadow" in delivery_note
    store.close()


def test_signoff_refuses_a_request_that_still_has_steps_left(tmp_path):
    settings, store = _store(tmp_path)
    created = intake(settings, store)
    access = next(r for r in created if r.kind == "access")
    with pytest.raises(GdprError):
        signoff(store, settings, access.id)
    store.close()


def test_each_checklist_step_records_who_and_when(tmp_path):
    settings, store = _store(tmp_path)
    created = intake(settings, store)
    rectification = next(r for r in created if r.kind == "rectification")
    request, narration = process_next_step(store, settings, rectification.id)
    assert narration
    first = request.checklist[0]
    assert first["done"] is True
    assert first["done_by"] == "agent"
    assert first["done_at"]
    store.close()
