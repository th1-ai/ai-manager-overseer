# Workflow: first-run setup

Objective: get AI Manager / Overseer from a fresh clone to a working demo,
then to real config, in one sitting.

## Steps

1. **Install and check.**
   ```bash
   make setup
   make doctor
   ```
   `make setup` creates the virtualenv, installs `requirements.txt`, and
   copies `.env.example` -> `.env` and every `config/*.example.yaml` ->
   `config/*.yaml` (only if those files do not exist yet - it never
   overwrites your own copies). `make doctor` will show a `FAIL` on "hotel
   identity" right after setup - that is expected, it means the property
   name is still the shipped placeholder. Everything else should be `ok` or
   `warn`.

2. **Run the demo.** No credentials needed.
   ```bash
   make demo
   ```
   Expect to see 6 sample drafts screened by the Warden (one passed, one
   blocked, two held, two escalated) and 4 sample emails opened as GDPR
   requests by the Notary, ending in the line
   `DEMO OK — 10 items processed, 10 drafted, 0 sent (shadow)`. If you do
   not see that, stop and read `workflows/99-troubleshooting.md` before
   going further.

3. **Fill in the property.** Edit `config/hotel.yaml` (name, address,
   contact, languages). Then:
   ```bash
   cp knowledge/property.example.md knowledge/property.md
   cp knowledge/faq.example.md      knowledge/faq.md
   cp knowledge/allergens.example.md knowledge/allergens.md
   cp knowledge/retention-policy.example.md knowledge/retention-policy.md
   cp knowledge/gdpr-intake-phrases.example.md knowledge/gdpr-intake-phrases.md
   cp knowledge/signature.example.md knowledge/signature.md
   ```
   Replace the sample content with the real property's facts. The
   `allergens.md` file matters more here than in most repos: it is what
   decides whether an allergen claim gets confirmed or escalated - see
   `docs/safety.md`.

4. **Wire up the draft feed.** `config/agent.yaml: draft_feed` starts on
   `adapter: mock`, which only ever screens the bundled sample drafts.
   `docs/integrations.md` covers pointing it at a real drop folder once you
   have another agent (or a small script) writing draft records there.

5. **Pick how the daily note thinks.** `config/hotel.yaml`'s `llm.provider`
   starts as `interactive` - it is the only LLM call in this repo
   (`tools/digest.py`, the daily governance note) and it asks you, in this
   Claude Code session, instead of calling a model. `docs/how-it-works.md`
   and `docs/safety.md` explain the other three providers.

6. **Re-check.**
   ```bash
   make doctor
   ```
   Once the property name is real and `knowledge/property.md` exists, the
   "hotel identity" and "knowledge" lines turn green. Move on to
   `workflows/10-screening.md` to run the Warden's loop for real.
