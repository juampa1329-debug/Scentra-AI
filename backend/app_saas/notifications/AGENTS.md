# Notifications AGENTS

Scope: internal SaaS notifications only.

## Rules

- Internal notifications are not customer conversations.
- Do not write internal notices into `saas_conversations`, `saas_messages`, webhook queues, triggers, remarketing, or AI pending replies.
- Always filter tenant reads by both `tenant_id` and `user_id`.
- Admin send actions must stay auditable and role-gated.
- Email copies are best-effort transactional notifications; failed email delivery must not block in-app delivery.

## Dangerous Zones

- Inbox UX: render notifications as pseudo-items only, never as replyable threads.
- AI runtime: notifications must remain invisible to customer-facing agents and automation.
- Bulk sends: keep recipient resolution bounded and deduplicated.
