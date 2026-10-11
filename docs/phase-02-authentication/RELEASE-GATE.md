# Phase02 acceptance / exit gate

| ID | Target | Current evidence | Status |
|---|---|---|---|
| AT-02-01 | password/hash, expiry, single use, registration race | Password/verification/replay/unit+HTTP synthetic; actual parallel register race not measured | PARTIAL |
| AT-02-02 | register→verify→login→me→logout; reset/revoke | Offline TestClient synthetic | PASS (offline only) |
| AT-02-03 | CSRF, Secure cookie, anti-enumeration, brute limits | Offline negative TestClient; SMTP/outbox live missing | PARTIAL |
| AT-02-04 | cross-user owner/role spoof | User session role verified; SQL owner scope Phase01 only, no Phase03 HTTP owner endpoints | PARTIAL |
| REGRESSION | full repo Python+JS/build | Not run in complete checkout | NOT RUN |
| SMTP | private credentials, SPF/DKIM/DMARC, bounce policy | No real provider/credentials | NOT RUN |
| PRODUCTION | real DB copy migrate/restore and full staging | No DB access or approval | BLOCKED |
| MFA | 2FA setup/recovery | Explicitly disabled/omitted pending product decision | NOT IMPLEMENTED |

Never label Phase02 as DONE_VERIFIED until all mandatory gates verified with an authorized staging environment and operational sign-off.
