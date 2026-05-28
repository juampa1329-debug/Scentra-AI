# Social AGENTS

Scope: SaaS social comments and AI-assisted replies.

Active path: `saas-version/backend/app_saas/social`.

## Real Structure

- Router prefix: `/social`.
- `service.py` handles non-prefixed tables `social_posts`, `social_comments`, and `comment_ai_settings`.
- Uses integration config tokens, AI settings/gateway, and comment reply/react provider calls.

## Rules

- Treat non-`saas_` table names as collision-prone.
- Preserve tenant filters on all social queries.
- Do not expose/decrypt tokens except at provider-call boundary.
- Keep comment AI settings tenant scoped.
- Do not auto-reply unless existing setting and endpoint behavior allow it.

## Dangerous Zones

- Runtime table creation for non-prefixed tables.
- Page access token lookup.
- Reply/react provider calls.
- AI suggestion storage and status.
- Ads/social overlap for comments.

## Required Checks

- Inspect migrations, `ads/router.py`, integrations config, and AI gateway before changes.
- Update `docs/KNOWN_ISSUES.md` if table-collision risk changes.

