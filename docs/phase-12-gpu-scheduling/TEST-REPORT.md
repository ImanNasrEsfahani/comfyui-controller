# Phase12 tests (isolated local suite)

Source revision `cc9cb4d6980f7d1300afc14e93b0291e36386be8`; Python 3.13, SQLite memory backed fixtures, FastAPI TestClient, Node 22.16 (no R2/GPU/provider). UTC evidence is in `evidence/`.

| Group | Local result | Scope |
| --- | --- | --- |
| Python scheduler/API/migration/installer | 50 PASS | SQL A/B, ownership, fair turns, quota, compatibility, stale heartbeat, stop/start guards, scale idempotency, usage separation, HTTP auth/CSRF, local guard transforms |
| Node frontend client | 6 PASS | explicit route allowlist, cookies/cache-control, CSRF, safe errors; no DOM rendering |
| Syntax | PASS | Python compile and TS JSX parse on five files |

Baseline negative test reproduced before implementation: importing absent `scheduler_v12` fails (see `evidence/BEFORE.txt`). Initial Python test runs caught incorrect SQL placeholder count, wrong TestClient thread fixture setup, request annotation issue, double Installer patch; each was corrected and **the final complete suite was rerun**. Do not count failing intermediate runs as successful acceptance.

**NOT RUN**: full current-repository backend pytest / regression, complete frontend `npm run build`, simulated or real Worker claim, provider calls and remote start/stop confirmation, multi-process SQLite contention/load, mobile 360px, RTL accessibility E2E, Salad R2/GPU and cost/invoice verification, exact complete-checkout Installer. No previous-phase regression claimed.

**Source caveat:** GitHub current `main.py` is still legacy original, and prior composite installer has not been tested on complete current checkout. The Phase12 installer verifies committed SHA/blobs and permits frontend ZIP overlay only when byte-identical; then reuses Stage11 transform, then adds the route; never run it blind in production.
