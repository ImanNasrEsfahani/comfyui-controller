# Delivery / deployment / rollback — Phase 00

## Package deployment

**No executable deployment or server restart required.** This ZIP contains docs + opt-in read-only tools/tests only, overlaid at repository-relative paths. Review unpacked files before copying. GitHub source SHA at investigation was `bea004d97a264f892cfae6dec9c4f691aed40a39`. If remote HEAD changed, repeat inventory before accepting these reports as current. Do **not** copy stale reports over later reviewed revisions.

Example local review only:

```bash
unzip -l comfyui-phase00-baseline.zip
unzip comfyui-phase00-baseline.zip -d /tmp/phase00-reviewed
# Review manifest + diff before placing files into checkout.
```

To test locally after unpacking package (Python >=3.11 and `boto3` for the mock R2 count test):

```bash
python3 -m unittest discover -s tests -p 'test_phase00_baseline.py' -v
```

## To establish operational baseline in a future authorized window

1. Verify deployed `git rev-parse HEAD`, `docker compose config --services` and profile `direct` manually. **Never publish `.env` values**, credentials or docker inspect payloads containing secrets.
2. For SQLite running in WAL mode, make a **consistent** database copy by SQLite online backup API under an authorized maintenance procedure. Do not rely on `cp` of only the `.db` while writers run; journal `-wal` may have uncheckpointed transactions. Preserve a separate versioned original backup.
3. Copy the verified database backup out to an isolated offline analysis directory and run:

```bash
python3 scripts/phase00_db_audit.py \
  --database-copy /path/to/offline/staging/controller-copy.db \
  --acknowledge-isolated-copy --restore-drill \
  --out /path/to/private-evidence/phase00-db-report.json
```

4. To count R2 objects (metadata only), run `phase00_r2_count.py` **only** after explicit operational authorization with private credentials configured; the script performs `ListObjectsV2` and prints prefix counts, no `GetObject`/download. Store the resulting counts privately. It doesn't assert tenancy/permissions.
5. Compare approved Salad image digest, group, model manifests and cache sizes via provider read-only interfaces; **never start/stop** GPU as part of Phase 00.

## Application rollback

No backend/frontend/DB/Worker changes shipped => there is **no runtime rollback action** for this documentation package. Revert these new documents/scripts from a working copy if needed. A production rollback (future phases) MUST restore a **proven** versioned SQLite snapshot and matched SHA/image digest only after draining/capturing current jobs; never replace a live WAL database ad hoc.
