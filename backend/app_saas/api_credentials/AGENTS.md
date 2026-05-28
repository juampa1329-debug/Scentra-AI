# API Credentials AGENTS

Scope: tenant API/TTS/provider credentials.

Active path: `saas-version/backend/app_saas/api_credentials`.

## Real Structure

- Router prefix: `/api-credentials`.
- Stores encrypted provider secrets.
- Exposes credential list/upsert and provider model lookup.
- Used by AI gateway, AI agent, social AI, and provider integrations.

## Rules

- Use `encrypt_secret` for incoming secrets and preserve masked-secret update behavior.
- Use `decrypt_secret` only at provider-call boundary.
- Never return raw secrets to frontend.
- Keep credential keys/provider codes compatible with frontend provider choices.
- Preserve owner/admin restriction on credential upsert.

## Dangerous Zones

- Model lookup with decrypted token.
- Secret overwrite when frontend sends masked placeholder.
- Provider code normalization.

## Required Checks

- Search provider code usage in `ai_gateway`, `ai_agent`, `social`, `advisor`, `agents`, and frontend settings.

