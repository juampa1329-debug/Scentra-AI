# Shared AGENTS

Scope: shared SaaS backend utilities.

Active path: `saas-version/backend/app_saas/shared`.

## Real Structure

- `security.py`: Argon2 password hashing, JWT, tenant/platform auth contexts, role dependencies, webhook secret helpers.
- `secrets.py`: Fernet encryption/decryption/masking for stored provider secrets.
- `captcha.py`: captcha verification.
- `security_events.py`: security/rate-limit event support.
- `request_meta.py`: request metadata.

## Rules

- Do not weaken JWT issuer/type validation.
- Do not change role hierarchy without checking all `require_role` and `require_platform_role` usages.
- Never log decrypted secrets.
- Preserve `enc:v1:` secret prefix and masked secret behavior.
- Keep tenant auth (`AuthContext`) separate from platform admin auth (`PlatformAuthContext`).
- Keep security changes backward compatible with existing tokens unless explicitly rotating auth.

## Dangerous Zones

- `SAAS_JWT_SECRET`, `SAAS_SECRET_KEY`, and Fernet derivation.
- Password verification exception handling.
- Webhook HMAC signature verification.
- Rate-limit/captcha toggles.

## Required Checks

- `rg "get_current_user|require_role|get_current_platform_admin|require_platform_role|decrypt_secret|encrypt_secret" saas-version/backend/app_saas`
- Update risk docs for any auth/secret behavior change.

