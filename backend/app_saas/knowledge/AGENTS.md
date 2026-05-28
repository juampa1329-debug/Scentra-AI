# Knowledge AGENTS

Scope: SaaS knowledge/RAG source ingestion, chunking, search, and reindexing.

Active path: `saas-version/backend/app_saas/knowledge`.

## Real Structure

- Router prefix: `/knowledge`.
- Handles source listing, upload, URL ingestion, search, health, source reindex, global reindex, and delete.
- Runtime SQL creates/checks knowledge source/chunk/retrieval log tables.
- Used by AI agent/advisor context flows.

## Rules

- Keep all sources/chunks tenant scoped.
- Do not ingest arbitrary remote content without preserving validation/safety pattern.
- Preserve source status lifecycle during upload/reindex/delete.
- Keep search result shape compatible with AI callers.
- Do not add vector DB assumptions unless code actually introduces one.

## Dangerous Zones

- File parsing and text extraction.
- URL ingestion.
- Reindex operations.
- Search scoring/context returned to AI.
- Runtime schema creation.

## Required Checks

- Search `knowledge_context_for_query` and `/knowledge/search` consumers.
- Update DB docs if knowledge schema changes.

