# Workflow: working the review queue

Objective: turn a held draft into a decision - release it or reject it -
and honestly simulate pausing the agent that produced it, when that is
warranted.

Nothing the Warden held or escalated moves without this. Releasing does not
send anything itself (the Warden does not own the originating agent's
channel) - it records that a human checked the draft and notifies the duty
manager, guarded exactly like every send in this family.

## Steps

1. **See what is waiting.**
   ```bash
   make review
   ```
   Each line shows the item id, its status (always `needs_human` here), the
   verdict the Warden gave it, which agent drafted it, and the guest.

2. **Read one in full.**
   ```bash
   python3 tools/review.py show <id>
   ```
   Prints the original draft text and the Warden's verdict with its
   evidence - both prices, the confidence score, the exact rule names that
   fired. Summarise this for the hotel in plain language; do not paste the
   raw JSON at them unless they ask for it.

3. **Decide.**
   ```bash
   python3 tools/review.py release <id> [--note "checked against the PMS"]
   python3 tools/review.py reject <id> --reason "wrong tone"
   ```
   `release` is "a human checked the rate against the PMS and it goes out as
   written" - it records `approved` and attempts the duty-manager
   confirmation (blocked in `mode: shadow`). `reject` leaves the hold
   standing; the originating agent's draft is never sent from here either
   way, because this repo never owns that send - it owns the gate.

4. **Pause the agent that produced it, if warranted.**
   ```bash
   python3 tools/review.py pause "Front Desk AI" --reason "watching a spike in complaints"
   python3 tools/review.py fleet
   python3 tools/review.py resume "Front Desk AI"
   ```
   Read the printed warning every time: this is honestly simulated. It
   records the state here; it does not reach Front Desk AI's own process.
   Tell the hotel exactly that before they rely on it.

## Rules

- Only `tools/review.py` writes `approved` / `rejected` on a screened item.
- A draft the Warden marked `escalated` for a human-only category
  (complaint, refund, legal, payment, safety, press, large group, medical)
  or an unverified allergen claim should never be released without actually
  reading it - these are exactly the cases the roster promise
  ("won't silently override a human decision") exists for.
- Confirm with the hotel before releasing anything, even a routine one, the
  first few times. `workflows/90-go-live.md` covers when to stop doing
  that.
