# R2 inventory: metadata only

Source uses `inputs/{uuid}/...` and `outputs/{job_id}/...`; these paths are **not owner-private by themselves** in a multi-user design. `phase00_r2_count.py` uses `ListObjectsV2` pagination **only** and produces aggregate counts. It does not perform `GetObject`, download or print object keys. Do not run without authorized provider access and budget/permission approval.

1. Keep credentials in the private runtime environment; never run `env`/`printenv`, upload `.env` or include R2 keys in CI.
2. Run manually on authorized server only: `python3 scripts/phase00_r2_count.py`.
3. Record total objects and counts by `inputs/`, `outputs/`, other, plus observed UTC and permission evidence. A count does not establish object ownership or ACL correctness.
4. Do not delete, rewrite, upload or generate signed media URLs during Phase 00.
5. A future signed-URL negative test requires user A/B and a controlled account fixture; not part of R2 inventory.

**As of this report:** production R2 inventory = **NOT RUN / UNKNOWN**.
