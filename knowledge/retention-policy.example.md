# Retention policy - Hotel Aurora

<!--
Copy this to knowledge/retention-policy.md. This is the human-readable
explanation behind `config/agent.yaml: gdpr.retention_holds` - the Notary
(`tools/gdpr.py`) reads the config for the actual numbers it enforces on an
erasure request; this file is what a guest, a colleague or your lawyer reads
to understand where those numbers come from. Keep the two in sync: if you
change a `days`/`basis` value here, change it in `config/agent.yaml` too.
-->

## What we keep, and why

| Record | Kept for | Legal basis |
|---|---|---|
| Invoices and other tax-relevant financial records | 10 years (3650 days) | Statutory tax retention - invoices cannot be deleted early even on an erasure request; this is what `gdpr.retention_holds` in `config/agent.yaml` enforces. |

## What an erasure request actually erases

When a guest exercises their right to erasure, the Notary removes everything
it is not legally required to keep: the marketing profile, preference notes,
free-text comments and anything in the guest messaging archive - and adds the
guest's contact details to a suppression list so they cannot be re-imported by
a later booking sync. Records under a retention hold above (invoices) stay,
and the requester is told in writing, by name, what was kept and why.

## Reviewing this file

Retention periods are set by your accountant or your lawyer, not by this
agent. Revisit this file (and the matching `config/agent.yaml` block) whenever
your statutory retention obligations change, or at least once a year.
