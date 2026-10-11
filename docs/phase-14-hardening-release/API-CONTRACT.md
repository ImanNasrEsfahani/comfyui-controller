# API and OpenAPI audit contract

This package does not invent API mounts. Run on the **complete exact SHA checkout**:

```bash
python3 scripts/phase14_api_inventory.py --repo . --output qa/api-static.json
PYTHONPATH=backend python3 scripts/phase14_api_inventory.py --repo . --runtime --output qa/openapi-import.json
```

The first reads/parses `backend/app/main.py`, matching registered router aliases. The second imports `app.main` in the isolated test environment and fingerprints the FastAPI OpenAPI output. **Neither performs an HTTP call**, so neither proves ingress routing, cookies, CSRF or actual data isolation.

Minimum API categories in release matrix: public/auth, authenticated account, owner-only jobs and assets, admin RBAC, worker service-only claims/progress/finalizing, video optional. Verify direct HTTP for each method with A, B, anonymous, admin and Worker identities; assert consistent `401`, `403`, `404`, `409`, `422`, `429`, `5xx` and no raw error contents.

Backend currently has a legacy `main.py` with **zero** `include_router(...)` calls; the proposed `phase14_prepare_checkout.py` exports candidate stitched versions for review only. The new signed Worker Claim continues to respond 503. Until runtime import after integration shows all required routes, do not claim API parity.

Keep v1 routes for existing Worker until a fully validated v2 cutover; never expose `DIRECT_WORKER_TOKEN` or `APP_INTERNAL_TOKEN` in user JavaScript. Generate OpenAPI fingerprint for each deployed SHA after staged restart; preserve route order to avoid shadowed dynamic routes.
