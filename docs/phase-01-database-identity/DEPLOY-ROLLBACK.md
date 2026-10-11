# Deploy & Rollback — Phase01 (NO PRODUCTION AUTHORIZATION)

This is a **staging-only rehearsal plan**. The requirement to prove restore of the actual DB and explicit owner mapping still blocks production.

1. Make clean Git checkout of pinned main SHA (`48b0bb50fe3cd582f37e9049a3988a83db9c4a24`); extract this ZIP into checkout, preserving relative paths. Review diffs. Confirm `.env` is private and staging network cannot talk to Salad/R2 production.
2. Create an isolated consistent SQLite backup with the online API (example staging DB path; substitute your local copy):
   ```bash
   python scripts/phase01_database.py backup-copy --source /safe/test/staging.sqlite --destination /safe/test/phase01-copy.sqlite
   python scripts/phase01_database.py migrate-copy --copy /safe/test/phase01-copy.sqlite
   python scripts/phase01_database.py migrate-copy --copy /safe/test/phase01-copy.sqlite
   ```
3. On *local checkout*, only after a successful on-copy migration, generate full drop-in files with SHA-pinned guard:
   ```bash
   python scripts/phase01_prepare_checkout.py             # verifies hashes only
   python scripts/phase01_prepare_checkout.py --apply     # rewrites 2 local files
   git diff -- backend/app/db.py backend/app/job_records.py
   ```
4. Confirm SQL helper patch, run on COPY only:
   ```bash
   python scripts/phase01_database.py activate-scoped-index --copy /safe/test/phase01-copy.sqlite --patched-job-records backend/app/job_records.py --patched-db backend/app/db.py
   ```
5. Run full repository regressions with exact CI `PYTHONPATH=backend python -m pytest -q tests tests/check_frontend_backend_upgrade.py`, `node --test tests/*.mjs`, `npm --prefix frontend install --no-audit --no-fund && npm --prefix frontend run build` in offline/staging environment with pinned dependencies. Record backend+Worker compatibility and deployed app SHA separately.
6. Only after approved legacy owner audit, create admin on isolated copy: `python scripts/phase01_seed_admin.py --copy /safe/test/phase01-copy.sqlite --email <verified> --display-name <display> --evidence-ref <private-reference> --approver <approver> --verified-out-of-band`; password entered via TTY. **Do not** run in production from this plan.
7. Quarantine all orphan/unmapped assets and compare per-table counts, object keys, secrets, stdout. Public signup flag remains OFF. If any A/B leak, abort.

Rollback rehearsal for no new identity data:
```bash
python scripts/phase01_database.py downgrade-empty-copy --copy /safe/test/phase01-copy.sqlite
```

If sessions/users/verified owners were created, downgrade **refuses**; restore the tested backup copy instead. A future production rollback MUST also coordinate active Worker leases and worker callbacks, DB WAL and deployed backend version. Do not use `docker compose down -v`, destructive SQL, raw file overwrite during WAL, or delete R2 objects.
