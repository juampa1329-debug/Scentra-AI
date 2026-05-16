# WhatsApp Cloud API webhook subscription flow

Scentra is multi-tenant: every tenant can connect a different WhatsApp Business Account (WABA), phone number, app ID and permanent access token. The platform must validate the WABA subscription to the Meta app because a WABA can send outbound messages and receive delivery statuses while inbound customer messages never arrive if the WABA is not subscribed through `/{WABA_ID}/subscribed_apps`.

## Automatic flow

1. The tenant saves or updates the Meta WhatsApp Cloud integration after onboarding or Embedded Signup.
2. Scentra reads the tenant-specific `business_account_id` / `waba_id`, `app_id`, `graph_api_version` and encrypted access token.
3. Scentra calls `ensure_webhook_subscription(waba_id, access_token)`.
4. The helper calls `GET /{WABA_ID}/subscribed_apps`.
5. If the configured app is already present, it returns `already_subscribed` and does not write duplicates.
6. If the WABA has no matching subscription, Scentra calls `POST /{WABA_ID}/subscribed_apps`.
7. Scentra verifies again with `GET /{WABA_ID}/subscribed_apps`.
8. The result is stored in `saas_whatsapp_subscription_checks` and also cached in the integration config as `last_webhook_subscription_check`.
9. The same validation runs when the user syncs phone numbers from Meta.

## Debug endpoint

The tenant admin can run:

```http
GET /saas/v1/internal/whatsapp/check-subscription?wabaId=YOUR_WABA_ID
Authorization: Bearer <tenant_jwt>
```

The response includes:

- WABA ID checked.
- Connected Meta App ID.
- Whether the WABA is subscribed.
- Whether auto-subscribe was attempted.
- Meta response for `subscribed_apps`.
- Phone numbers associated with the WABA.
- Local webhook endpoint status.
- Recent subscription logs.

## Error handling

The helper classifies common Meta errors into operational statuses:

- `token_expired_or_invalid`: OAuth token expired, invalid or revoked.
- `insufficient_permissions`: token lacks WhatsApp management/messaging permissions or app access.
- `waba_not_found_or_not_accessible`: WABA ID is wrong, belongs to another business, or token cannot access it.
- `rate_limited`: Meta rate limit or throttling.
- `meta_oauthexception`: another Meta OAuthException.
- `network_or_unknown_error`: timeout or network issue.

Temporary Meta failures are retried with exponential backoff.

## Symptom detector

The diagnostics overview checks recent webhook payloads. If statuses arrive but inbound message webhooks do not, Scentra returns:

```json
{
  "whatsapp_symptoms": {
    "statuses_without_inbound": true,
    "recommendation": "Llegan statuses de Meta, pero no llegan mensajes entrantes. Verifica WABA subscribed_apps, callback URL, token de verificacion y campo messages en la app de Meta."
  }
}
```

This does not prove `subscribed_apps` is the only cause, but it is the first automatic check because it matches the production symptom: outbound delivery statuses work while customer messages never reach the SaaS.

## What Scentra can sync from Meta

Scentra can build a Meta Sync Center for tenant admins. With the right system user token and app permissions it can verify or sync:

- WABA subscription to the app.
- Phone numbers under the WABA.
- Phone number registration status.
- Message templates and approval status.
- Webhook delivery symptoms received by Scentra.
- Commerce/catalog data if the tenant connects WooCommerce, Shopify or supported Meta commerce assets.

Some Meta Developers settings still require manual approval/configuration in Meta, especially app review, permission approval, business verification and any asset the token cannot access. Scentra can detect, guide and fix what Graph API permits, but it cannot bypass Meta permissions.

## References

- Meta Graph API WABA subscribed apps edge: https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account/subscribed_apps/
- Meta WhatsApp Cloud API webhooks: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/
- Meta WhatsApp Business phone numbers: https://developers.facebook.com/docs/whatsapp/business-management-api/manage-phone-numbers/
