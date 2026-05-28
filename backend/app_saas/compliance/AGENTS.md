# Compliance Domain Rules

Scope: `app_saas/compliance/`.

- Keep all exports tenant-scoped through `AuthContext.tenant_id` and `set_tenant_context`.
- Privacy delete endpoints must create auditable requests only; never hard-delete CRM, messages, or AI memory without explicit user approval and a dedicated migration/workflow.
- Customer exports may include conversation memory and sampled agent memory metadata, but must not expose decrypted secrets or provider credentials.
- Preserve role gates: account self-export is any authenticated user; customer export is owner/admin/supervisor; delete requests are owner/admin.
- New compliance actions must be idempotent, auditable, and compatible with clean PostgreSQL bootstrap.
