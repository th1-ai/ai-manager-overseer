# Workflow: shadow to live

Objective: decide, together with the hotel, whether the duty-manager alerts
and (if the Notary is on) the GDPR delivery emails are ready to really go
out, instead of only being recorded - and make the change safely if so.

This is the hotel's decision, never the agent's. Do not suggest it until the
checklist below is genuinely true, and when you do raise it, say plainly
what changes: the Warden itself never sends a guest-facing message either
way - only the duty-manager notification and the Notary's requester
correspondence are gated by `mode`.

## Checklist

- [ ] `make doctor` is clean (no `FAIL` lines). `warn` on `mode` is expected
      until you flip it.
- [ ] `config/hotel.yaml` has the real property name, address and contact
      details, and `knowledge/property.md`, `knowledge/allergens.md` and
      `knowledge/retention-policy.md` exist and are accurate (not the
      shipped examples) - the allergen check and the erasure outcome both
      quote them directly to a human.
- [ ] At least a few days of real `make run` passes have gone through the
      review queue, not just the demo fixtures, and the hotel has watched
      the Warden catch (or miss) something real.
- [ ] `systems.messaging.adapter` is a real one (`unipile` or `webhook`) and
      `make doctor` shows it healthy - going live on `mock` would only ever
      touch the fixtures.
- [ ] If the Notary is enabled: `systems.email.adapter` is a real mailbox,
      `knowledge/signature.md` has the AI-disclosure line (`docs/safety.md`
      has suggested wording), and at least one real request has been walked
      end to end and signed off in shadow mode so the outcome text has been
      checked by a human.
- [ ] A duty manager knows what the release/reject/pause commands do and
      that pause is simulated (`workflows/80-review.md`).

## Making the change

1. Edit `config/hotel.yaml`:
   ```yaml
   mode: live
   ```
2. `review.require_approval_for` still lists `send_message` and
   `send_email` by default - it should. Going live means a released hold's
   duty-manager alert, and a signed-off request's delivery email, actually
   go out; it does not change which drafts the Warden holds, and it does
   not let the Warden draft or send a guest-facing reply itself.
3. Run `make doctor` again to confirm.
4. Clear the shadow-era backlog so nothing old releases by surprise:
   ```bash
   python3 tools/review.py stale
   ```
5. Run one real pass and manually watch a release go through:
   ```bash
   make run ARGS="--limit 1"
   python3 tools/review.py list
   python3 tools/review.py release <id>
   ```
6. Tell the hotel exactly what just changed: a released hold's duty-manager
   alert, and a signed-off GDPR request's delivery email, now really leave
   the building. Everything the Warden holds still needs a human to release
   it - going live does not loosen a single rule threshold.

## Going back to shadow

```yaml
mode: shadow
```
in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env` for one run. Either
stops every outbound notification and delivery on the next pass, mid-
schedule, with no other change required. The screening rules themselves are
never affected by `mode` - they run identically in shadow and live.
