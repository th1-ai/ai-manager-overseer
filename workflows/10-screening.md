# Workflow: the screening loop

Objective: run one pass over the drafts waiting to be screened and see what
the Warden did with each one.

## Inputs

- A configured `draft_feed` (`config/agent.yaml`) - `mock` by default, which
  only ever screens the bundled fixtures. See `docs/integrations.md` to
  point it at a real drop folder.
- The rule thresholds and lists in `config/agent.yaml`:
  `confidence_threshold`, `rate_block_threshold_pct`,
  `rate_held_threshold_pct`, `category_blocks`, `allergen_check`,
  `tone_check`. The defaults work; tune them once you have watched a few
  real passes.

## Steps

1. **Run one pass.**
   ```bash
   make run
   make run ARGS="--limit 5"       # just the first five drafts
   make run ARGS="--dry-run"       # compute everything, write nothing
   ```
   Every draft gets the same five checks, always in this order: category
   block, allergen/safety, rate cross-check, confidence gate, tone check -
   see `docs/how-it-works.md`. Nothing here calls a model; there is no
   `interactive` pause on this path.

2. **See what happened.**
   ```bash
   make review
   ```
   A draft that passed every check is `auto_sent` - it needed no human
   touch and is off the list. Anything `blocked`, `held_rule` or
   `escalated` is `needs_human`, on purpose, with the duty manager already
   notified (or the notification recorded as blocked, in shadow mode).

3. **Work the queue.** `workflows/80-review.md` covers release / reject /
   pause in full.

4. **Keep it running.**
   ```bash
   make watch                       # loop on the configured interval
   ```
   Or schedule it - `make schedule ARGS="--all"` prints one snippet per job
   in `config/agent.yaml: schedule`, including this one
   (`schedule.screening`, every 2 minutes by default - "the instant
   something looks off" is the roster promise, and guest-facing drafts are
   time-sensitive).

## Edge cases

- **No new drafts.** `make run` prints `0 items processed, 0 drafted, 0
  sent` and exits 0. Nothing to do.
- **A draft with no price or room type.** The rate cross-check is skipped
  for that draft (`tools/engine.py:check_rate` returns `{}`); the other
  four checks still run.
- **A re-run sees the same draft again.** `tools/engine.py:process_draft`
  skips anything the store has already screened - see
  `core.store.Store.upsert_item` and `already_processed`.
- **A stale item stuck at `sending`.** `tools/run.py` calls
  `store.reap_stuck_sending()` on every pass, same as every repo in this
  family, though the Warden itself never moves an item to `sending` (see
  `workflows/80-review.md` on `release`).
