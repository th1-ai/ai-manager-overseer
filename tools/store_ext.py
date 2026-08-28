"""tools/store_ext.py - this agent's own tables, added beside core's with
``store.migrate()`` (ARCHITECTURE.md section 5). Two tables:

``gdpr_requests``  the Notary's request desk - one row per statutory request,
                   with a JSON checklist that is walked one step at a time
                   (docs/how-it-works.md design decision 13).
``agent_fleet``    the Warden's honestly-simulated pause/resume state - see
                   docs/how-it-works.md design decision 7.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.store import Store, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS gdpr_requests (
  id                 TEXT PRIMARY KEY,
  source_email_id    TEXT,
  kind               TEXT NOT NULL,
  requester          TEXT NOT NULL,
  requester_email    TEXT,
  received_at        TEXT NOT NULL,
  sla_days           INTEGER NOT NULL,
  status             TEXT NOT NULL DEFAULT 'open',
  checklist_json      TEXT NOT NULL,
  result_summary     TEXT,
  sensitivity_reason TEXT,
  assigned_to        TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  UNIQUE (source_email_id)
);
CREATE INDEX IF NOT EXISTS idx_gdpr_status ON gdpr_requests (status, received_at);

CREATE TABLE IF NOT EXISTS agent_fleet (
  agent_name    TEXT PRIMARY KEY,
  status        TEXT NOT NULL DEFAULT 'active',
  paused_at     TEXT,
  paused_by     TEXT,
  paused_reason TEXT,
  resumed_at    TEXT,
  resumed_by    TEXT,
  updated_at    TEXT NOT NULL
);
"""

GDPR_STATUSES = ("open", "in_progress", "awaiting_counsel", "awaiting_signoff", "done")


def migrate(store: Store) -> None:
    store.migrate(SCHEMA)


@dataclass
class GdprRequest:
    id: str
    source_email_id: str | None
    kind: str
    requester: str
    requester_email: str
    received_at: str
    sla_days: int
    status: str
    checklist: list[dict] = field(default_factory=list)
    result_summary: str | None = None
    sensitivity_reason: str | None = None
    assigned_to: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "GdprRequest":
        return cls(id=row["id"], source_email_id=row["source_email_id"], kind=row["kind"],
                   requester=row["requester"], requester_email=row["requester_email"] or "",
                   received_at=row["received_at"], sla_days=row["sla_days"], status=row["status"],
                   checklist=json.loads(row["checklist_json"] or "[]"),
                   result_summary=row["result_summary"], sensitivity_reason=row["sensitivity_reason"],
                   assigned_to=row["assigned_to"], created_at=row["created_at"],
                   updated_at=row["updated_at"])


def create_gdpr_request(store: Store, *, source_email_id: str | None, kind: str, requester: str,
                        requester_email: str, received_at: str, sla_days: int,
                        checklist: list[str]) -> tuple[GdprRequest, bool]:
    """Ledger-style: one request per ``source_email_id``. Returns ``(request, created)``."""
    if source_email_id:
        row = store.db.execute("SELECT * FROM gdpr_requests WHERE source_email_id=?",
                               (source_email_id,)).fetchone()
        if row is not None:
            return GdprRequest.from_row(row), False
    req_id = f"gr-{uuid.uuid4().hex[:10]}"
    now = utcnow()
    items = [{"step": s, "done": False, "done_at": None, "done_by": None} for s in checklist]
    store.db.execute(
        "INSERT INTO gdpr_requests (id, source_email_id, kind, requester, requester_email, "
        "received_at, sla_days, status, checklist_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (req_id, source_email_id, kind, requester, requester_email, received_at, sla_days,
         "open", json.dumps(items, ensure_ascii=False), now, now))
    return get_gdpr_request(store, req_id), True  # type: ignore[return-value]


def get_gdpr_request(store: Store, request_id: str) -> GdprRequest | None:
    row = store.db.execute("SELECT * FROM gdpr_requests WHERE id=?", (request_id,)).fetchone()
    return GdprRequest.from_row(row) if row else None


def list_gdpr_requests(store: Store, *, status: str | None = None) -> list[GdprRequest]:
    if status:
        rows = store.db.execute(
            "SELECT * FROM gdpr_requests WHERE status=? ORDER BY received_at ASC",
            (status,)).fetchall()
    else:
        rows = store.db.execute(
            "SELECT * FROM gdpr_requests ORDER BY received_at ASC").fetchall()
    return [GdprRequest.from_row(r) for r in rows]


def update_gdpr_request(store: Store, request_id: str, **fields: Any) -> GdprRequest | None:
    cols, params = [], []
    mapping = {"checklist": "checklist_json"}
    for key, value in fields.items():
        col = mapping.get(key, key)
        if col not in ("status", "checklist_json", "result_summary", "sensitivity_reason",
                       "assigned_to"):
            raise ValueError(f"cannot set '{key}' on a gdpr_requests row")
        cols.append(f"{col}=?")
        params.append(json.dumps(value, ensure_ascii=False) if col == "checklist_json" else value)
    if not cols:
        return get_gdpr_request(store, request_id)
    params += [utcnow(), request_id]
    store.db.execute(f"UPDATE gdpr_requests SET {', '.join(cols)}, updated_at=? WHERE id=?", params)
    return get_gdpr_request(store, request_id)


# -- fleet (pause/resume, simulated) --------------------------------------
def get_fleet_status(store: Store, agent_name: str) -> dict:
    row = store.db.execute("SELECT * FROM agent_fleet WHERE agent_name=?",
                           (agent_name,)).fetchone()
    return dict(row) if row else {"agent_name": agent_name, "status": "active"}


def list_fleet(store: Store) -> list[dict]:
    return [dict(r) for r in store.db.execute(
        "SELECT * FROM agent_fleet ORDER BY agent_name ASC").fetchall()]


def pause_agent(store: Store, agent_name: str, *, actor: str, reason: str) -> dict:
    now = utcnow()
    store.db.execute(
        "INSERT INTO agent_fleet (agent_name, status, paused_at, paused_by, paused_reason, "
        "updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(agent_name) DO UPDATE SET "
        "status='paused', paused_at=excluded.paused_at, paused_by=excluded.paused_by, "
        "paused_reason=excluded.paused_reason, updated_at=excluded.updated_at",
        (agent_name, "paused", now, actor, reason, now))
    store.record_event(None, actor, "agent_paused_simulated", {"agent": agent_name, "reason": reason})
    return get_fleet_status(store, agent_name)


def resume_agent(store: Store, agent_name: str, *, actor: str) -> dict:
    now = utcnow()
    store.db.execute(
        "UPDATE agent_fleet SET status='active', resumed_at=?, resumed_by=?, updated_at=? "
        "WHERE agent_name=?", (now, actor, now, agent_name))
    store.record_event(None, actor, "agent_resumed_simulated", {"agent": agent_name})
    return get_fleet_status(store, agent_name)
