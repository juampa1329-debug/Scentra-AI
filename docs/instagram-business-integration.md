# Instagram Business integration for Scentra

Scentra now supports a multi-tenant Instagram Business onboarding flow using Facebook Login, Graph API discovery, Page subscribed apps validation and the existing Scentra webhook/inbox/outbound pipeline.

## Required platform environment variables

These are platform-level variables. The client does not need to know them.

```env
SCENTRA_META_APP_ID=your_meta_app_id
SCENTRA_META_APP_SECRET=your_meta_app_secret
SCENTRA_INSTAGRAM_WEBHOOK_VERIFY_TOKEN=random_platform_verify_token
SCENTRA_API_PUBLIC_URL=https://api.scentra-ai.online
SCENTRA_APP_PUBLIC_URL=https://app.scentra-ai.online
SCENTRA_META_GRAPH_VERSION=v24.0
```

## One-time Meta app configuration

The Scentra operator configures this once in Meta Developers:

- Facebook Login redirect URI: `https://api.scentra-ai.online/saas/v1/integrations/instagram/oauth/callback`
- Instagram webhook callback URL: `https://api.scentra-ai.online/saas/v1/webhooks/instagram`
- Instagram webhook verify token: value of `SCENTRA_INSTAGRAM_WEBHOOK_VERIFY_TOKEN`
- App permissions requested by Scentra:
  - `instagram_basic`
  - `instagram_manage_messages`
  - `pages_manage_metadata`
  - `pages_messaging`
  - `pages_read_engagement`
  - `business_management`

Clients do not need Graph Explorer, manual IDs, or manual `subscribed_apps` configuration once the platform app is approved and configured.

## Tenant onboarding flow

1. Tenant admin opens `Ajustes > Canales > Instagram Business`.
2. Tenant clicks `Conectar con Facebook Login`.
3. Scentra creates a short-lived OAuth state in `saas_instagram_oauth_states`.
4. Facebook Login returns to Scentra's OAuth callback.
5. Scentra exchanges the code for a token and discovers:
   - `GET /me/businesses`
   - `GET /{business-id}/owned_pages`
   - page-linked `instagram_business_account`
   - fallback `GET /me/accounts`
6. Scentra shows detected pages and Instagram Business accounts.
7. Tenant selects the Instagram account to connect.
8. Scentra stores the selected Page/Instagram data in `saas_integrations` with encrypted tokens.
9. Scentra creates a tenant-local Instagram webhook endpoint for observability.
10. Scentra validates and repairs Page app subscription with:
    - `GET /{page-id}/subscribed_apps`
    - `POST /{page-id}/subscribed_apps?subscribed_fields=messages,messaging_postbacks,comments,mentions`

## Webhook architecture

Instagram uses the global callback:

```http
POST /saas/v1/webhooks/instagram
```

Scentra maps each incoming event to a tenant by matching the event IDs against connected integrations:

- `config_json.instagram_business_account_id`
- `config_json.page_id`

Matched events are inserted into `saas_webhook_events` using provider `instagram`, then processed by the existing embedded worker or worker container.

## Inbox and outbound

Inbound Instagram DMs, comments and mentions are normalized into the same tables used by WhatsApp:

- `saas_conversations`
- `saas_messages`

Outbound Instagram DMs reuse:

- `saas_outbound_messages`
- `process_due_outbound_messages()`

For this phase, text DMs are enabled through the Instagram/Messenger send endpoint using the encrypted Page access token. Media sending can be added next with attachment upload/reusable attachment handling.

## Diagnostics

Endpoint:

```http
GET /saas/v1/integrations/instagram/diagnostics
Authorization: Bearer <tenant_jwt>
```

Returns:

- Page ID
- Instagram Business Account ID
- username
- callback URL
- tenant webhook status
- Page `subscribed_apps` status
- permissions response
- last received Instagram conversation
- recent webhook errors
- subscription repair logs

The frontend exposes this in `Ajustes > Canales > Instagram Business > Diagnostics IG`.

## Auto-repair

Scentra automatically retries Page subscription checks when:

- the tenant connects an Instagram asset
- diagnostics are run
- Meta returns temporary/rate-limit style errors

Logs are stored in `saas_instagram_subscription_checks` with:

- Page ID
- Instagram Business ID
- app ID
- HTTP status
- Meta error code/type/message
- whether auto-subscribe was attempted
- final subscribed state

## Troubleshooting

If DMs do not arrive:

1. Run `Diagnostics IG` in Scentra.
2. Check `subscribed_apps` status.
3. Confirm the global webhook callback has recent `last_seen_at`.
4. Confirm the Page/Instagram ID in the payload matches the connected tenant integration.
5. Confirm Meta app permissions are approved and the client granted them during Facebook Login.
6. Confirm the connected Instagram is a Business or Creator account linked to a Facebook Page.

If OAuth detects pages but no Instagram account, the Page likely has no Instagram Business Account linked or the Facebook user lacks sufficient business/page permissions.

## References

- Meta Instagram Platform and Graph API: https://developers.facebook.com/docs/instagram-platform/
- Messenger API support for Instagram: https://developers.facebook.com/docs/messenger-platform/instagram/
- Facebook Login permissions: https://developers.facebook.com/docs/permissions/reference/
- Page subscribed apps edge: https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/
- Webhooks for Meta apps: https://developers.facebook.com/docs/graph-api/webhooks/
