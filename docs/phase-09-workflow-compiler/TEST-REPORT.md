# Phase09 test report — 2026-10-11 UTC, local synthetic fixtures

Base source SHA: `3d7e2539cec80f7087188101fd30b38f161011ec`. Only GitHub read operations. Local Python 3.13 / FastAPI 0.128.2 / Pydantic 2.13.5 / httpx 0.28.1 / Node.js 22.16.0 / TypeScript parser 5.8.x. Runtime test dependencies differ from lock-pinned requirements; do not infer CI success.

**Before work:** GitHub tree did not include `backend/app/workflow_compiler.py`, new Phase09 version tables or a semantic compiler route. Legacy graph template and Phase08 parameter intent existed, but no verified transactional integration into owner-only Job creation. No baseline runnable Phase09 failure test was available; missing feature was reproduced by source inspection, not by staging HTTP.

**Exact commands executed** in the local working folder:

```shell
python -W ignore::ResourceWarning -m unittest discover -s tests -p 'test_phase09_*.py' -v
node --test tests/test_phase09_frontend.mjs
python -m compileall -q backend/app/workflow_compiler.py backend/app/workflow_api.py backend/app/migrations/phase09.py scripts/phase09_prepare_checkout.py scripts/phase09_migrate_copy.py tests/test_phase09_*.py
```

| Acceptance ID | Synthetic result | Production / E2E status | Evidence |
| --- | --- | --- | --- |
| AT-09-01 golden txt2img, img2img, multi-ref, image2video, text2video | PASS structural only | NOT RUN on real Worker | `evidence/PYTHON-TESTS.txt`, `workflow_templates` |
| AT-09-02 cycles, unknown nodes, types/ports, invalid dimensions, cross-user refs | PASS synthetic | LoRA model/node and GPU compatibility NOT RUN | `evidence/PYTHON-TESTS.txt` |
| AT-09-03 request key replay, content hash, new prompt, stored snapshot immutable | PASS nonexecuting | Accepted Job creation and retry NOT RUN | `evidence/PYTHON-TESTS.txt` |
| AT-09-04 legacy /api paths untouched and metadata immutability | PASS source-level + SQL trigger | Full legacy/Worker contract and historic Job Retry NOT RUN | `evidence/PYTHON-TESTS.txt` |

**Last run results:** Python **47 tests passed**, JavaScript **10 tests passed**, Python compileall PASS, TypeScript JSX syntax check PASS (five files). No known failing required local security test in this isolated suite. These are not end-to-end production acceptance.

**NOT RUN:** full GitHub checkout install+test (DNS unavailable), full previous-phase Python/Node regressions, `npm ci && npm run build`, actual React browser render, mobile 360px RTL/LTR, screen-reader, real two-session R2/Salad/Worker execution, Phase07 signature/node evidence, GPU, provider deployment rollback and exact compiled graph checksum in ComfyUI `/prompt`.

The TestClient injection for user A/B and Superadmin is explicitly mocked (not real cookie validation), and compatibility rows are explicitly *synthetic*. The tests prove this module's ownership/query and gating behavior under fixture contracts only. Frontend JS tests are client-module/syntax tests, not Vite build or browser UI.

**Decision: PARTIAL / BLOCKED, never `DONE_VERIFIED` until the entire required E2E acceptance matrix passes with observed Worker input and historical Retry proof.**
