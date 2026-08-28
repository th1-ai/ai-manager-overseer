# Guardrails and safety

This agent talks to your guests and touches your systems. Everything below is
built in, not optional, and this page explains what it does and what is left for
you to decide.

## The two modes

| Mode | What happens |
|---|---|
| `shadow` (default) | The agent reads, thinks, drafts and queues. It **never** sends a message and **never** writes to your PMS. Approving, editing or rejecting a draft records your decision (and teaches the agent) but sends nothing. At go-live, `python3 tools/review.py stale` clears that shadow-era queue so nothing old goes out by surprise. |
| `live` | Items you approved are really sent. Everything else still waits. |

`mode` lives in `config/hotel.yaml`. It is a global kill switch: flipping it back
to `shadow` stops every outbound action immediately, mid-schedule, with no other
change. `config/agent.yaml` can be stricter than `hotel.yaml`, never looser.

Two more brakes:

- `make run ARGS="--dry-run"` computes everything and writes nothing, even in
  live mode. Use it when you change a prompt.
- `review.require_approval_for` in `config/hotel.yaml` lists the actions that
  need a human even in live mode. The defaults are `send_email`, `send_message`,
  `pms_write`, `payment`, `publish`. Shortening that list is how you hand the
  agent more rope, one action at a time.

Every outbound action in the codebase goes through one function,
`core/review.py:assert_write_allowed`. There is no second path.

## The five screening checks

`tools/engine.py:screen_draft()` runs every draft through five checks, in
this fixed order, none of them a model call:

1. **Category block** (`category-blocks`) - a draft whose category is
   human-only (`complaint, refund, legal, payment, safety, press,
   large_group, medical`) is always `escalated`, whatever its confidence.
2. **Allergen/safety claim check** (`allergen-check`) - a dietary or
   allergen assertion not confirmed, close to verbatim, in
   `knowledge/allergens.md` is `escalated`. This is deliberately the
   highest-severity check in the repo.
3. **Rate cross-check** (`rate-crosscheck`) - a quoted price compared to
   the PMS rate for the same room type and dates; a large gap blocks, a
   smaller one holds.
4. **Confidence gate** (`confidence-gate`) - below
   `config/agent.yaml: confidence_threshold` (80% by default) is blocked.
5. **Tone check** (`tone-check`) - a forbidden phrase or a shouting line
   holds.

Every rule that fires is named in the verdict, with the evidence (both
prices, the score, the phrase) - "won't silently override a human decision;
when it intervenes, it says what it caught and why" is enforced exactly
here, not just promised. See `docs/how-it-works.md` for the full decision
table.

## The review queue

Nothing a screened draft's own agent wanted to send goes out without
passing through this.

```bash
make review                        # what is waiting
python3 tools/review.py show <id>   # the full draft and the Warden's evidence
python3 tools/review.py release <id> [--note "checked against the PMS"]
python3 tools/review.py reject <id> --reason "wrong tone"
```

A screened draft moves `new -> needs_human` (or straight to `auto_sent` if
nothing fired) and waits. Only `tools/review.py` writes `approved` /
`rejected` on it. `release` never re-drafts anything and never sends a
guest-facing message itself - it records the human decision and attempts
the duty-manager confirmation, guarded exactly like a send anywhere else in
this family.

**Pause is honest.** `python3 tools/review.py pause "<agent>" --reason
"..."` records that state here and says plainly, every time, that it does
not reach the named agent's own process - this repo cannot switch another
repo off. Real fleet control needs that agent's own kill switch.

## What this agent will not do

- Screen anything while `mode: shadow` and then release it without a human
  - the release itself is what shadow blocks, not the screening.
- Draft or send a guest-facing reply itself, ever, for either the Warden or
  the Notary - the Warden only ever holds or clears another agent's own
  draft, and the Notary only ever delivers the outcome of a request a human
  signed off.
- Let a human-only category (complaint, refund, legal, payment, safety,
  press, large group, medical) or an unverified allergen claim reach a
  guest as an AI answer, whatever the confidence score says.
- Auto-process a GDPR request whose text matches a sensitivity keyword - it
  parks at `awaiting_counsel` until a human assigns it.
- Deliver a GDPR request's outcome without a human sign-off
  (`python3 tools/gdpr.py signoff <id>`) - see `docs/how-it-works.md` design
  decision 17.
- Delete a financial record under legal hold on an erasure request -
  `config/agent.yaml: gdpr.retention_holds` names what stays and why.
- Take a payment, issue a refund, or move money. Payment adapters are
  read-only by design.
- Invent a fact that is not in `knowledge/` or in the draft/request it was
  given.

## Data handling

**What leaves your machine.** With `llm.provider: anthropic` or `claude-code`,
the prompt goes to Anthropic. That prompt contains the guest message and the
relevant property facts. With `llm.provider: mock` or `interactive`, nothing
leaves the machine at all.

**What is stored, and where.** Everything lives in `data/` inside this folder:
`agent.db` (SQLite), `logs/*.jsonl`, `exports/`. `data/` is gitignored. There is
no cloud service behind this repo and no telemetry.

**Card numbers are redacted on the way in.** Every inbound message passes through
`core/redact.py` before it is stored, logged or put into a prompt. A payment card
number is replaced with `[CARD REDACTED ****1234]`, and labelled CVC and expiry
values in the same message go with it. Detection requires a real card prefix and
a valid Luhn checksum, so booking references and door codes survive. IBANs are
masked the same way. Nothing you can do in config turns this off.

**Retention.** `privacy.retention_days` (default 365) is how long processed items
stay in the database. Deleting `data/agent.db` deletes everything the agent knows.

## GDPR, in practice

This section is about how running this software makes you compliant, not
about the Notary's own job of *working* a guest's GDPR request (that is
`workflows/20-compliance-gdpr.md` and `docs/how-it-works.md`). Both matter.
If you are in the EU or handle EU guests' data, the short version:

- **You are the controller.** This software runs on your machine, under your
  control, on your data. TH1 does not receive it.
- **Your model provider is a processor.** If you use the `anthropic` or
  `claude-code` provider, Anthropic processes guest data on your behalf. Check
  their data processing terms and record them in your processing register.
- **Purpose and minimisation.** The agent sees the message and the property facts
  it needs. Do not put staff phone numbers, card data or full guest histories in
  `knowledge/`.
- **Right to erasure.** A guest asking to be deleted means removing their rows
  from `data/agent.db` and any exported CSVs. Ask your Claude session:
  *"Delete every item in data/agent.db whose payload mentions this email address,
  and tell me how many rows you removed."*
- **Retention.** Set `privacy.retention_days` to what your own policy says, not
  to the default.

This is a practical summary, not legal advice.

## Telling guests they are talking to AI

The EU AI Act (Article 50) requires that a person is told when they are
interacting with an AI system, unless it is obvious. Whether it applies to you
depends on where you and your guests are, but it is good practice everywhere and
guests react well to it.

Add a line like this to the signature of any message the agent sends
(`knowledge/signature.md`):

> This reply was prepared with AI assistance and reviewed by our team. Reply to
> this message any time to reach a person directly.

If you run in live mode with auto-send for some intents, say so plainly:

> This reply was written by our AI assistant. If you would rather speak to a
> person, just say so and we will take over.

Keep the escape hatch in the sentence. A guest who wants a human should never
have to work out how to get one.

## Subscription or API: an honest note

Two ways to pay for the reasoning:

**Your Claude Code subscription** (`llm.provider: claude-code` or `interactive`).
Flat monthly cost, no per-message billing. This is genuinely the cheapest way to
run a small hotel's agent.

The caveat, plainly: a personal Pro or Max subscription is intended for
interactive use, and Anthropic's usage policy and rate limits apply to automated
use of it. A handful of scheduled runs a day is a normal way to work. Pointing
a busy inbox at it around the clock is not, and you will hit rate limits at the
worst moment. Read the terms and decide for yourself.

**The Anthropic API** (`llm.provider: anthropic`). Pay per token, no ambiguity
about automated use, proper rate limits, and usage you can attribute. This is
the right answer for production volume. `make report` shows what you are
spending.

Start on the subscription while you are learning what the agent does. Move to the
API when it becomes part of how the hotel runs.

## If something goes wrong

1. `mode: shadow` in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env`. Every
   outbound action stops on the next pass.
2. Remove the schedule (`crontab -e`, `launchctl unload`, or
   `systemctl disable --now <slug>.timer`).
3. `make doctor` to see what the agent thinks its state is.
4. `data/logs/*.jsonl` has every decision, with the run id, in order.
