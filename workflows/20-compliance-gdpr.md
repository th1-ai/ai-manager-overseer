# Workflow: Compliance / GDPR AI (the Notary)

Objective: turn on the privacy desk, catch a statutory request in the
inbox, and work it to a signed-off close.

The Notary is **off by default** (`config/agent.yaml:
subagents.compliance_gdpr.enabled`). The Warden is fully useful without it -
screening does not need the privacy desk - so only turn this on once you
want requests worked here rather than by hand. See `docs/sub-agents.md`.

## Turning it on

1. In `config/agent.yaml`, set `subagents.compliance_gdpr.enabled: true`.
2. Fill in `knowledge/gdpr-intake-phrases.md`, `knowledge/retention-policy.md`
   and `knowledge/allergens.md`'s sibling for this desk if your legal team
   wants different wording than the shipped examples - `config/agent.yaml:
   gdpr.retention_holds` is what `tools/gdpr.py` actually reads, so keep the
   two in sync.
3. `make doctor` - the "compliance/gdpr sub-agent" line checks every kind
   has a checklist configured.

## Steps

1. **Catch requests in the inbox.**
   ```bash
   python3 tools/gdpr.py intake
   ```
   Reads `systems.email.adapter` for anything shaped like an access, erasure
   or rectification request (`knowledge/gdpr-intake-phrases.md`) and opens a
   request with a live SLA countdown. Anything else in the inbox is left
   alone - this is not a general mail classifier.

2. **See what is open.**
   ```bash
   python3 tools/gdpr.py list
   ```
   Red under 7 days left. A request whose text mentions a sensitivity
   keyword (`config/agent.yaml: gdpr.sensitivity_keywords`) shows
   `awaiting_counsel` instead of being worked automatically.

3. **Work a request.**
   ```bash
   python3 tools/gdpr.py show <id>          # the full checklist and evidence
   python3 tools/gdpr.py step <id>          # one checklist item at a time
   python3 tools/gdpr.py run <id>           # every step up to (not) sign-off
   ```
   Every step records `done_at` and `done_by`. `run` stops at
   `awaiting_signoff` and prints the outcome - it never delivers anything by
   itself.

4. **Assign a sensitive request.**
   ```bash
   python3 tools/gdpr.py assign <id> --to "duty manager"
   ```
   Only legal from `awaiting_counsel`. Read the request first - the
   sensitivity keyword that tripped it is in `show <id>`.

5. **Sign off.** The one human gate in this repo.
   ```bash
   python3 tools/gdpr.py signoff <id>
   ```
   Read the outcome in `show <id>` first. This is the only command that
   marks a request `done` and attempts the delivery email - guarded and
   blocked in `mode: shadow`, exactly like every send in this family.

6. **The SLA digest.**
   ```bash
   python3 tools/gdpr.py sweep
   ```
   Every open request's days left; alerts the duty manager on anything at
   two days or under. This is `config/agent.yaml: schedule.compliance_gdpr`.

## Edge cases

- **A request past its deadline.** `sla_days_left` goes negative; `sweep`
  and `list` both show it plainly rather than clamping it to zero.
- **`signoff` before every other step is done.** Refused with a clear
  `GdprError` naming what to run first - see `docs/how-it-works.md` design
  decision 17.
- **Press or legal requests.** Not one of the three kinds this repo
  processes. Route them to a human by hand; see `docs/how-it-works.md`
  design decision 16 for why the promise is narrowed here.
