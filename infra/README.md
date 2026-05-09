# Infra SaaS (lineamientos iniciales)

## Componentes objetivo
1. `api` (web requests).
2. `webhook-ingest` (entrada de eventos).
3. `workers` (campaigns, remarketing, dispatch, billing).
4. `postgres` administrado.
5. `queue + dlq`.
6. `object storage`.
7. `secret manager`.
8. `observabilidad`.

## Ambientes
1. `dev`
2. `staging`
3. `prod`

## Requisitos minimos
1. HTTPS obligatorio.
2. Secretos fuera de codigo.
3. Backups y restauracion probados.
4. Alertas de disponibilidad y errores.
