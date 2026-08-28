#!/usr/bin/env python3
"""tools/doctor.py - is AI Manager / Overseer configured and reachable right now?

    make doctor
    python3 tools/doctor.py

Runs the generic core.doctor checks (python, deps, config, .env, hotel
identity, mode, llm provider, every adapter, the store, knowledge) plus this
agent's own: the rule thresholds, the prompt files, and - only when the
Notary sub-agent is enabled - its checklists and intake phrases. Exits 0
when everything passed, 1 when a FAIL line needs fixing. Never a traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.doctor import Check, FAIL, PASS, WARN, print_table, run_checks  # noqa: E402


def check_thresholds(settings: Settings) -> Check:
    conf = settings.agent_get("confidence_threshold", None)
    block = settings.agent_get("rate_block_threshold_pct", None)
    held = settings.agent_get("rate_held_threshold_pct", None)
    if conf is None or block is None or held is None:
        return Check("rule thresholds", FAIL, "confidence_threshold or the rate thresholds "
                    "are missing from config/agent.yaml",
                    "Copy config/agent.example.yaml to config/agent.yaml.")
    if held >= block:
        return Check("rule thresholds", FAIL,
                    f"rate_held_threshold_pct ({held}) must be lower than "
                    f"rate_block_threshold_pct ({block})",
                    "Fix the two values in config/agent.yaml.")
    return Check("rule thresholds", PASS,
                f"confidence gate {conf}%, rate held >= {held}%, rate blocked >= {block}%")


def check_prompts() -> Check:
    missing = [p for p in ("prompts/governance-note.md", "prompts/schemas/governance-note.json")
              if not (REPO_ROOT / p).is_file()]
    if missing:
        return Check("prompts", FAIL, f"missing {', '.join(missing)}",
                    "These ship with the repo - restore them from git.")
    return Check("prompts", PASS, "governance-note.md + schema present")


def check_knowledge_files() -> Check:
    names = ("allergens", "gdpr-intake-phrases", "retention-policy")
    missing = [n for n in names if not (REPO_ROOT / "knowledge" / f"{n}.example.md").is_file()]
    if missing:
        return Check("agent knowledge", FAIL, f"missing example file(s): {', '.join(missing)}",
                    "These ship with the repo - restore them from git.")
    real = [n for n in names if (REPO_ROOT / "knowledge" / f"{n}.md").is_file()]
    if not real:
        return Check("agent knowledge", WARN, "only the shipped .example.md files exist",
                    "Copy knowledge/allergens.example.md etc. and fill in your own facts "
                    "before you rely on the allergen check or the GDPR retention text.")
    return Check("agent knowledge", PASS, f"{len(real)}/{len(names)} filled in")


def check_gdpr(settings: Settings) -> Check:
    enabled = bool(settings.agent_get("subagents.compliance_gdpr.enabled", False))
    if not enabled:
        return Check("compliance/gdpr sub-agent", PASS, "off (default) - see docs/sub-agents.md")
    checklists = settings.agent_get("gdpr.checklists", {}) or {}
    missing = [k for k in ("access", "erasure", "rectification") if not checklists.get(k)]
    if missing:
        return Check("compliance/gdpr sub-agent", FAIL,
                    f"enabled, but gdpr.checklists is missing: {', '.join(missing)}",
                    "Fill in config/agent.yaml: gdpr.checklists for every kind.")
    return Check("compliance/gdpr sub-agent", PASS,
                f"on - {len(checklists)} checklist(s) configured")


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        checks = run_checks(None) + [Check("config", FAIL, str(exc),
                                          "Fix config/hotel.yaml or config/agent.yaml.")]
        return print_table(checks, title="AI Manager / Overseer - doctor")

    checks = run_checks(settings, extra=[check_thresholds, check_gdpr])
    checks.append(check_prompts())
    checks.append(check_knowledge_files())
    return print_table(checks, title="AI Manager / Overseer - doctor")


if __name__ == "__main__":
    raise SystemExit(main())
