# Future frontend type/client contract (NO frontend runtime changes)

At present `frontend/src/App.jsx` still uses `X-Internal-Token` for private operations. **Phase01 intentionally creates no new login UI or public auth endpoint.** Client transition must wait until per-resource SQL authorization and cookie/CSRF middleware are enforced on every private endpoint in a future phase.

Proposed future types (design only; not implemented here):

```ts
type PublicUser = { id: string; display_name: string; email_verified: boolean; roles: string[] }
type SessionState = { authenticated: false } | { authenticated: true; user: PublicUser }
type OwnedJob = { id: string; owner_user_id: string; state: string; snapshot_version: number }
type OwnedAsset = { asset_id: string; owner_user_id: string; availability: 'available'|'quarantined'|'deleted' }
```

The UI must never allow a browser-supplied `owner_user_id` to control server assignment. Cookies should be `HttpOnly; Secure; SameSite=Lax/Strict` under single-origin `/api` with CSRF protection for state changes; server decisions supersede any frontend permission gate. Change account -> invalidate all per-user caches, drafts, signed URLs, object URLs and localStorage saved prompts. No GPU provider/admin credentials are exposed to user browsers.
