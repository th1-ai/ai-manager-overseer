# Workflow: troubleshooting

Read the whole error before doing anything - every tool here is written to
say what broke and what to do about it. If you fix something not covered
below, add it here.

## `make doctor` shows a FAIL

Each `FAIL` line has a `->` fix hint right under it. Common ones:

- **`hotel identity`: name is still 'The Marlow House'.** Expected on a
  fresh clone. Edit `config/hotel.yaml`.
- **`rule thresholds`: rate_held_threshold_pct must be lower than
  rate_block_threshold_pct.** Fix the two numbers in `config/agent.yaml` -
  held catches the smaller gaps, blocked catches the larger ones.
- **`compliance/gdpr sub-agent`: enabled, but gdpr.checklists is missing.**
  You turned the Notary on without filling in `config/agent.yaml:
  gdpr.checklists` for all three kinds - copy them back from
  `config/agent.example.yaml`.
- **An adapter shows FAIL, not warn.** `universal`/`built` adapters fail
  loud when misconfigured (a `warn` is reserved for stubs). Read the
  `detail` column - it names the missing file or variable.

## `make demo` does not print `DEMO OK`

- Make sure `make setup` ran first (`.venv` must exist).
- `tools/demo.py` forces `llm.provider=mock` and reads
  `fixtures/inbound/drafts/*.json` and `fixtures/inbound/*.json` - if you
  deleted or renamed those files, restore them from git.
- Read the traceback if there is one; `tools/demo.py` does not swallow
  errors on purpose, so a fixture problem shows up immediately.

## `python3 tools/digest.py` exits with code 3

Not an error. `llm.provider: interactive` parked a prompt. Read
`data/pending/*.prompt.md`, write your answer to the matching
`*.answer.json` (JSON only, matching the schema shown, no prose, no code
fence), and run the same command again.

## A screened draft is stuck at `sending`

A process died mid-release. `tools/run.py` calls
`core.store.Store.reap_stuck_sending()` on every pass, which moves anything
stuck for more than 30 minutes to `failed` so you see it rather than it
vanishing. In practice this should never happen for the Warden itself,
since `release` never claims an item into `sending` - it stays at
`approved`. If you do see it, it means something outside this repo called
`claim_for_send()` on the same database; check what else is pointed at
`data/agent.db`.

## `python3 tools/gdpr.py signoff <id>` refuses with a GdprError

The request still has undone steps. Run `python3 tools/gdpr.py show <id>`
to see which, then `python3 tools/gdpr.py run <id>` to finish them, then
sign off. A request `awaiting_counsel` needs `assign` first.

## The rate cross-check never fires

It only runs when a draft carries `quoted_price`, `room_type_id` and
`check_in` (`tools/engine.py:check_rate`), and only when
`systems.pms.adapter` actually has a rate for that room type and date -
`make doctor`'s `pms adapter` line shows what is loaded. A draft missing
any of the three fields is checked by the other four rules only, which is
correct, not a bug: not every draft quotes a price.

## `python3 tools/*.py` says `ModuleNotFoundError: No module named 'core'`

You ran it with a Python that is not the repo's virtualenv, or from outside
the repo root. Use `make run` / `make doctor` / etc. (they call
`.venv/bin/python` for you), or run `.venv/bin/python tools/run.py` directly
from the repo root.

## Still stuck

`data/logs/*.jsonl` has every decision the agent made, in order, with a run
id. `python3 tools/review.py show <id>` has the full evidence for one
screened draft; `python3 tools/gdpr.py show <id>` has the full checklist
for one privacy request. If neither explains it, that is a real bug -
describe exactly what you ran and what you expected, and ask.
