# Media Domain Rules

Scope: `saas-version/backend/app_saas/media/`.

## Source Of Truth

- Router: `router.py`.
- Media storage paths: local `saas_media_assets` and Meta/WhatsApp media helper paths in this router.
- Voice Intelligence persistence: `saas_voice_intelligence_analyses` from migration `060_saas_voice_intelligence_phase24.sql`.
- Vision Intelligence persistence: `saas_vision_intelligence_analyses` from migration `061_saas_vision_intelligence_phase24.sql`.
- Web/Image Search Intelligence persistence: `saas_web_search_intelligence_runs` and `saas_web_search_intelligence_results` from migration `062_saas_web_image_search_intelligence_phase24.sql`.
- Phase 24.6 Multimodal Memory persistence: `saas_multimodal_memory_events` from migration `064_saas_multimodal_memory_training_events_phase24.sql`; media routes may sync sanitized outputs to this table through `agents/multimodal_memory.py`.

## Required Checks

- Preserve tenant filters for every media/message query.
- Preserve role checks before exposing media or analysis.
- Verify message ownership before fetching or analyzing provider media.
- Keep AI Gateway payload logging safe: no raw audio/image/document bytes, no base64, no decrypted secrets, no provider media URLs containing secret-bearing query strings.
- Keep byte limits and demo/full gating before provider execution.
- Preserve cached analysis behavior unless the user explicitly requests reprocessing semantics.
- For external search, preserve public URL safety screening, tenant provider credential loading, and human approval status before any downstream use.
- Phase 24.5 agent tools may call this domain through `agents/multimodal_tools.py`; keep the same tenant ownership, feature gating, byte limits and approval rules.

## Safety Boundaries

- Media analysis may write media analysis rows and compact message payload metadata only.
- Do not send customer messages, mutate CRM, create tasks/tickets, execute campaigns, trigger workflows, assign agents or call tools from this domain without a separate approved ADR.
- Do not enable non-Google audio providers for Voice Intelligence until adapter/model support is validated with real credentials.
- Do not advertise non-Google document/OCR analysis until adapter/model support is validated with real credentials.
- Vision Intelligence must analyze existing tenant media only.
- Web/Image Search Intelligence may call approved search providers with explicit user queries, but must not crawl result URLs, auto-send links/images, or mark blocked results approved.
- Agent tool callers must not bypass search result approval. Only approved, non-blocked result rows may be used as agent prompt context.
- Multimodal memory sync must be best-effort from this domain. A memory/training capture failure must not convert a successful voice/vision/search action into a user-visible media failure.
- Do not mark media analysis rows as training-ready unless the Intelligence feature gate allows `multimodal_training_events`, `ml_predictions`, or `ai_premium`.
- Do not expand media fetching to arbitrary external URLs without SSRF review and allowlist/proxy design.
