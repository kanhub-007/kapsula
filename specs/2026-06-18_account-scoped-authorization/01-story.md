# Decision: No Per-Account Authorization Code (SE3 resolved by decision)

**Status:** Accepted
**Date:** 2026-06-18
**Closes:** SE3 (account-scoped authorization / IDOR) — by decision, not by code.

## Context

The comprehensive code review flagged SE3: resource-scoped API routes
(`/accounts/{id}`, `/collections/{id}`, `/documents/{id}`, search) load
by GUID with no ownership check, so any holder of `KAPSULA_API_KEY` can
read/mutate any account. The spec originally proposed a
`PrincipalResolver` + `OwnershipResolver` + `AuthorizationService`
stack and asked: *how does an authenticated caller map to account(s)?*

That question was the sole blocker. It has now been answered.

## Decision

**kapsula is single-tenant. Accounts are organizational units, not
security boundaries. No per-account authorization code will be written.**

Concretely:
- Each deployment has **one operator** (the party running the process).
- That operator may create and use **multiple accounts** (the Account →
  Collection → Document hierarchy is for organizing knowledge, as the
  README documents). Multiple accounts are fully supported and expected.
- There is **one principal per deployment** — the holder of
  `KAPSULA_API_KEY` (or, with no key set, the local loopback caller).
  That principal is trusted to access **every** account in the
  deployment, because all accounts belong to the same operator.
- Therefore there is no inter-account isolation to enforce. The existing
  `require_api_key` dependency **is the complete authentication and
  authorization story** for the API.

## What this means for the code

- **No new code.** The `PrincipalResolver` / `OwnershipResolver` /
  `AuthorizationService` sketched in earlier drafts of this spec are
  **not** built.
- The existing defenses remain in force and are sufficient:
  - Loopback bind by default (`API_HOST=127.0.0.1`).
  - Server refuses to bind `0.0.0.0`/`::` unless `KAPSULA_API_KEY` is set.
  - CORS allowlist (loopback by default; never `*` with credentials).
  - `hmac.compare_digest` constant-time key comparison (SE1, shipped).
- MCP is local/stdio — single principal by design; unaffected.

## Threat model (explicit)

| Threat | Status |
|--------|--------|
| Unauthenticated network access to an exposed API | Covered by `require_api_key` + bind guard + CORS |
| Timing attack on the API key | Covered by `hmac.compare_digest` (SE1) |
| One principal reading another principal's accounts | **Out of scope** — there is only one principal per deployment |
| Two mutually-distrusting parties sharing one process | **Out of scope** — not a supported deployment (see Future trigger) |

## Future trigger (when this decision would reverse)

If a deployment ever hosts accounts for **mutually-distrusting parties**
on one process, this model breaks: any party holding the shared key sees
every party's data. At that point, implement the original spec
(`PrincipalResolver` + per-resource `OwnershipResolver` +
`AuthorizationService`) with **Option B** (an `api_keys` table mapping
`key_hash → account_id[]`) or **Option C** (signed JWTs carrying an
`account_id` claim). The `PrincipalResolver` interface sketch keeps B/C
a drop-in.

This is a **deployment-shape** trigger, not a feature ask: as long as
the operator trusts themselves across all their own accounts, the
current model holds.

## Follow-up actions (non-code)
- [x] Update `auth.py` docstring to reflect this decision (remove the
      stale "IDOR prevention is a follow-up" line).
- [x] Update the comprehensive-review progress doc's deferred→spec
      mapping: SE3 → **resolved by decision**, no code.
