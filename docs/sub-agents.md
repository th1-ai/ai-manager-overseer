# Sub-agents in this repo

AI Manager / Overseer folds in one sub-agent. It shares this repo's
`core/`, `data/agent.db` and `config/agent.yaml` - there is nothing extra to
install. It is off by default; see `config/agent.yaml`'s `subagents` block.

## Compliance / GDPR AI - "The Notary"

**Does.** Catches GDPR/privacy/legal/press requests the moment they arrive
and works each one against the statutory clock, on a visible per-request
checklist: verify the requester's identity, locate the guest's data across
PMS, comms and billing archives, compile the export, redact third-party
data, check legal holds before any erasure, deliver via secure link.
Manages consent and retention rules, keeps a live days-left countdown on
every open request, and routes anything sensitive to a human instantly.

**Won't.** Never decides a legal question alone - it prepares, documents
and counts down; a human signs off before anything leaves.

**Why.** One mishandled data request is a real liability; this is the
seatbelt.

**Output.** 100% of sensitive requests caught and worked on a checklist;
nothing slips past day 30, audit trail by default.

**Off by default.** The Warden is fully useful on its own - screening
another agent's drafts does not need the privacy desk. Turn this on once
you want statutory requests worked here instead of by hand; see
`workflows/20-compliance-gdpr.md`.

**What it narrows from the promise above, on purpose** (see
`docs/how-it-works.md` for the reasoning behind each):

- Three request kinds only - `access`, `erasure`, `rectification`. A press
  or legal-shaped request is routed to `awaiting_counsel` for a human to
  handle, not given its own automated checklist.
- "The moment they arrive" means a keyword match against
  `knowledge/gdpr-intake-phrases.md` on every inbound email, not a general
  free-text classifier - tune the phrase list against your own traffic. The
  shipped list covers English plus es/fr/de/it/pt, and matching is accent-
  folded (`tools/gdpr.py:_fold()`), so a phrase written with or without its
  accent still matches a guest email typed the other way.
- "Routes anything sensitive to a human instantly" is
  `config/agent.yaml: gdpr.sensitivity_keywords` - a request matching one
  is held at `awaiting_counsel` until a human assigns it; it is not worked
  automatically past that point.
- A human sign-off (`python3 tools/gdpr.py signoff <id>`) gates every
  delivery - "a human signs off before anything leaves" is a real code
  path here, not just a sentence in this file.

## How the Warden and the Notary relate

They share this repo's `oversight_rules`-equivalent (`config/agent.yaml`),
the same database and the same daily governance note
(`tools/digest.py`, `prompts/governance-note.md`) - the note explicitly
reports where the privacy queue's deadlines stand alongside what the Warden
screened. Conceptually the Warden supervises what the other agents *do*;
the Notary supervises what the business *holds*. There is no code path
between them - a privacy erasure does not currently reach into the
Warden's own screening history or any other agent's memory, which would be
the natural next step for a deployment that runs both together at scale.
