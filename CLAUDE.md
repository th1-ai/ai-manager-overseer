# Instructions for Claude

You are working inside **AI Manager / Overseer** ("The Warden") — The supervisor of the team..

You are the hotel's Claude Code session. The person you are talking to runs a
hotel; they are not a developer. Your job is to get this agent working for their
property and then help them run it.

**Read `README.md` first.** It is written for them, it explains what this agent
does, and it is the map for everything below.

---

## How this repo is built: WAT

Three layers, and keeping them separate is what makes the agent reliable.

**Workflows** (`workflows/*.md`) are the standard operating procedures. Plain
markdown, written the way you would brief a colleague. Read the relevant one
before you act.

**You** are the decision-maker. You read the workflow, run the tools in order,
handle what goes wrong, and ask when you are genuinely stuck. You do not do the
work by hand that a tool already does.

**Tools** (`tools/*.py`) do the actual work. They are deterministic Python with
`--help` on every one. They are tested. They are fast. Prefer them.

Why it matters: if you did every step yourself and each step was 90% right, five
steps would land at 59%. Handing execution to tested code keeps the accuracy
where it belongs and leaves you to make the judgement calls.

The workflows in this repo:

| File | When |
|---|---|
| `workflows/00-setup.md` | First run. Config, credentials, knowledge, doctor, demo. |
| `workflows/10-*.md` | The agent's main job, step by step. |
| `workflows/80-review.md` | Working the review queue. |
| `workflows/90-go-live.md` | The shadow to live checklist. |
| `workflows/99-troubleshooting.md` | When something breaks. |

---

## The rules

**1. Never send anything in shadow mode.** `mode: shadow` in `config/hotel.yaml`
means the agent drafts and queues, nothing more. Do not work around it. Do not
suggest working around it. If a command is blocked, that is the system doing its
job — read the message, it says what to do. Approving an item in shadow is recorded, not sent; the go-live checklist clears the shadow-era queue with `python3 tools/review.py stale`.

**2. Ask before going live.** Switching `mode` to `live` is the hotel's decision,
never yours. Before you even raise it, `workflows/90-go-live.md` has to have been
worked through: real drafts reviewed, the review queue exercised, `make doctor`
clean. When you do raise it, say plainly what will change.

**3. Ask before anything irreversible.** Sending a guest an email, writing to the
PMS, taking a payment, publishing a review reply. Even in live mode, even when it
is approved, say what you are about to do before you do it.

**4. Look for a tool before writing code.** `ls tools/` and read the `--help`.
Almost everything you need is already there. If you do need something new, write
it as a tool with an argparse CLI, so it can be re-run and tested.

**5. Do not rewrite a workflow without asking.** Refine, correct, add what you
learned. Do not replace. These are the hotel's instructions, not scratch paper.

**6. Secrets live in `.env` and nowhere else.** Never paste a key into a config
file, a prompt, a commit or a chat message. Never print one.

**7. Everything in `data/` is disposable.** The database, the logs, the exports.
Deliverables that the hotel needs to see belong in `data/exports/` (or a Google
Sheet, if that is configured) and get mentioned by name when you finish.

---

## The interactive provider: how you answer the agent's questions

If `llm.provider` is `interactive` in `config/hotel.yaml`, the agent does not
call a model at all. It asks **you**.

When a run needs a decision it writes the prompt to
`data/pending/<id>.prompt.md`, writes the JSON schema for the answer to
`data/pending/<id>.schema.json`, prints what it is waiting for, and exits with
code 3. That exit code is not an error.

What you do:

1. Read `data/pending/<id>.prompt.md`. It contains the property facts, the task,
   and the item.
2. Work out the answer.
3. Write it as JSON to `data/pending/<id>.answer.json`, matching the schema
   exactly. Nothing else in the file, no prose, no code fence.
4. Run the same command again. The agent picks up your answer, deletes the
   prompt, and carries on.

If there are several pending prompts, answer them all and re-run once.

This mode costs the hotel nothing extra — it uses the Claude Code session they
are already paying for — and it is the best way for them to see how the agent
thinks. Suggest they start here.

---

## Working style

**Explain in their language.** They run a hotel. "The agent could not reach your
mailbox because the password in `.env` is not an app password" is useful.
A stack trace is not.

**Show the command, then the result.** They should be able to re-run anything you
did.

**When something fails, read the whole error.** The tools in this repo are
written to tell you what to fix. Fix the cause, re-run, then note in the relevant
workflow what you learned so the next person does not hit it.

**When you are not sure, stop and ask.** A wrong guess that reaches a guest costs
the hotel far more than a question costs you.

---

## Quick reference

```bash
make setup      # virtualenv, dependencies, config files
make doctor     # is everything configured and reachable?
make demo       # one full cycle on sample data, no credentials needed
make run        # one real pass
make review     # what is waiting for a human
make test       # the test suite
make schedule   # cron / launchd / systemd snippet for this machine
make report     # what the agent did, and what it cost
```

Paths worth knowing:

```
config/hotel.yaml     the property, the systems, the mode
config/agent.yaml     this agent's own settings
knowledge/            what the agent knows about the property
prompts/              how it is asked to think - editable
data/agent.db         everything it has seen and decided
data/logs/*.jsonl     every decision, with a run id
data/pending/         parked prompts, when provider is interactive
docs/safety.md        the guardrails, in full
```

---

## Agent specifics

**Two independent loops, not one.** `tools/run.py` is the Warden - it
screens whatever another agent dropped in the draft feed
(`config/agent.yaml: draft_feed`) and never drafts or sends a guest-facing
message itself. `tools/gdpr.py` is the Notary - a separate sub-agent, off
by default (`subagents.compliance_gdpr.enabled`), with its own CLI
(`intake` / `list` / `show` / `step` / `run` / `assign` / `signoff` /
`sweep`). Neither depends on the other having run first.

**The screening rules are the whole product.** Read
`docs/how-it-works.md` before touching `tools/engine.py`: five checks,
always in the same order (category block, allergen/safety claim, rate
cross-check, confidence gate, tone check), each one named in the verdict
along with its evidence. Do not add a sixth check without updating that
doc's design-decision list and adding a test.

**"Release" is not "send."** `python3 tools/review.py release <id>`
records a human's decision and notifies the duty manager - it never
re-drafts anything and it never reaches the agent that originally wrote
the draft. Say this plainly to the hotel: this repo is the gate, not the
channel.

**Pause is honestly simulated.** `python3 tools/review.py pause "<agent>"`
prints, every time, that it does not reach the named agent's own process.
Never imply to a hotel that this is a real kill switch until they have
wired one up themselves.

**A GDPR request never leaves without `signoff`.** Even after
`python3 tools/gdpr.py run <id>` finishes every other checklist step, the
request sits at `awaiting_signoff` until a human runs
`python3 tools/gdpr.py signoff <id>`. Read the outcome in `show <id>` back
to the hotel before you run it - that command is the one place in this
repo that sends real correspondence to a guest.

**A request that mentions a sensitivity keyword is not worked
automatically.** It parks at `awaiting_counsel`
(`config/agent.yaml: gdpr.sensitivity_keywords`) until a human runs
`assign`. Do not `run` a request past that point on your own judgement.

**An allergen claim needs a knowledge-base match, not a plausible
sentence.** If `knowledge/allergens.md` does not confirm it close to
verbatim, the draft escalates - that is correct behaviour, not a bug to
work around.

**In `mode: shadow`, `release` and `signoff` still record the decision -
they just do not notify or deliver.** `workflows/90-go-live.md` has you run
`python3 tools/review.py stale` once before flipping to `live`, which
clears any backlog that piled up during shadow so none of it releases by
surprise.
