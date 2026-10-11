# Decisions: require owner sign-off, do not invent values

The official `DECISIONS.md`, `GLOBAL-RULES.txt`, and approved owner backfill plan were not present in the reviewed source files. This table is **open**; illustrative defaults in previous code/tests are not approvals.

| ID | Decision required before release | Safe interim state |
|---|---|---|
| DEC-01 | Public vs invite-only signup | No public signup rollout |
| DEC-02 | SQLite WAL vs PostgreSQL + migration/load evidence | No high-concurrency SLA |
| DEC-03 | Studio authority and advanced nodes | Only restricted semantic drafts |
| DEC-04 | Shared or dedicated GPU pool | Shared planning only, dedicated OFF |
| DEC-05 | Numeric per-user concurrency/storage/GPU quotas | No invented account balances/quotas |
| DEC-06 | Original media and backup retention/delete grace | Soft-delete only, no destructive GC |
| DEC-07 | Cross-user sharing rules | Sharing OFF |
| DEC-08 | Supported models, license, image digest & VRAM | No model declared inference-ready |
| DEC-09 | GPU overhead and actual-vs-estimated cost attribution | Estimates labeled; invoice absent = unknown |
| DEC-10 | SMTP provider, bounce/outbox and domain | Unverified account email delivery |
| DEC-11 | Team/membership tenancy and ownership | Single owner scope only |
| DEC-12 | Prompt/EXIF/Seed embedding and metadata export | Private by default, no raw prompt export |
| DEC-13 | API versioning and worker compatibility | No automatic v1/v2 cutover |
| DEC-14 | License, Terms and Privacy obligations | Do not enable commercial multi-user signup |
| DEC-15 | Dedicated GPU Stop right, budget and TTL | Dedicated OFF |

Operational owners/reviewers must sign and version these separately. Recording this table does not resolve or approve them.
