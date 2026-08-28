# The business case

## Why it matters (roster, verbatim)

> It's the safety layer that lets you trust the doers. One agent watching
> all the others means you can run the team at full autonomy without
> turning risk up.

For the Notary specifically:

> One mishandled data request is a real liability; this is the seatbelt.

## What to expect (roster, verbatim)

> Watches the whole roster so you can run agents at full autonomy; targets
> <1 bad message ever reaching a guest.

> 100% of sensitive requests caught and worked on a checklist; nothing
> slips past day 30, audit trail by default.

## What to measure

`tools/report.py` (`make report`) reads straight from `data/agent.db`:

- **Screened, by verdict.** How many drafts passed straight through versus
  were held, blocked or escalated, and by which rule. This is the honest,
  measured version of the roster's `-99%` claim: how many bad messages were
  *caught*, which is what this repo can actually prove. Nothing here counts
  how many got through undetected, because nothing in a fresh clone could -
  see `docs/how-it-works.md` design decision 9.
- **Intervention rate.** Share of screened drafts that were not `passed`.
  Watch this over time per agent (`payload.agent` on each item): a rising
  rate for one agent is a real signal to look at its prompts, not just to
  keep releasing its drafts.
- **Privacy queue.** Open GDPR requests by status, the nearest deadline, and
  how many have breached. This is the Notary's version of "100% of
  sensitive requests caught and worked on a checklist."
- **Spend.** The one LLM call in this repo (`tools/digest.py`'s daily note)
  logs its usage the same way every repo in the family does.

## Honest caveats

- The Warden only screens what it is handed. If another agent never writes
  a draft record to the feed (`docs/integrations.md`), nothing about that
  agent's output is checked - a screening layer is only as complete as its
  wiring, and that wiring is greenfield in this repo (see
  `docs/how-it-works.md` design decision 1).
- "Wrong tone" and "a bad fact" are only two-fifths implemented: the rate
  cross-check and the allergen/safety claim check are real; a general
  tone classifier and a general fact-checker against a full knowledge base
  are not - see `docs/safety.md`.
- Pausing an agent is honestly simulated. It records the intent here; it
  does not reach another agent's process. Do not sell it as a real kill
  switch until your own deployment wires that up.
- The Notary's intake is a keyword classifier, not a general-purpose mail
  reader. A request phrased unusually will be missed - review the inbox by
  hand periodically, at least until you have tuned
  `knowledge/gdpr-intake-phrases.md` against real traffic.
