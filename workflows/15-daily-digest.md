# Workflow: the daily governance note

Objective: produce the one-a-day summary of what the Warden and the Notary
already decided, in plain prose.

This is what "runs the daily review loop" means in this repo
(`docs/how-it-works.md` design decision 6). Every number in the note comes
from `data/agent.db`; the model only turns it into a few sentences and is
told, verbatim, never to invent a name, a number or a rule
(`prompts/governance-note.md`).

## Steps

1. **Run it.**
   ```bash
   python3 tools/digest.py
   ```
   This is the only place in the repo that calls a model - screening and
   the checklist are both deterministic. With `llm.provider: interactive`
   (the default) this parks a prompt in `data/pending/` and exits 3; read
   it, write your answer as JSON to the matching `*.answer.json`, and run
   the same command again.

2. **Read the note back to whoever asked for it.** It says what was
   screened, what was held or escalated and why, and where the privacy
   queue's deadlines stand. If anything in it does not match what you saw
   in `make review` or `python3 tools/gdpr.py list`, that is a bug in the
   summary the note was built from - check `tools/digest.py:build_summary`
   before trusting the note.

3. **Schedule it.** `config/agent.yaml: schedule.daily_digest` runs this at
   08:00 by default - `make schedule ARGS="--all"` prints the exact snippet.

## Edge cases

- **A quiet day.** If nothing was screened and the privacy queue is empty,
  the note says so plainly rather than padding itself out - the prompt asks
  for facts, not colour.
- **`llm.provider: mock`.** Used by `make demo`/`make test` - always returns
  the same canned note from `fixtures/expected/governance-note/`. That is
  expected and is not a bug.
