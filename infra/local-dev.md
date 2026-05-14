# Local SaaS dev

## API + DB
1. Desde `saas-version/`:
   `docker compose -f docker-compose.saas.yml up --build`

2. La API aplica migraciones automaticamente antes de iniciar `uvicorn`.

   El perfil local aplica migraciones SaaS core. Las migraciones `002`, `003` y `004` son para convertir una base legacy existente.

3. Health:
   `http://localhost:8010/saas/v1/health`

## Frontend
1. Desde `saas-version/frontend/`:
   `npm install`

2. Arrancar:
   `npm run dev`

3. URL:
   `http://localhost:5174`

## Nota
Las migraciones `002`, `003` y `004` se aplican contra una base con las tablas legacy presentes.

## Prueba rapida del flujo webhook
1. Crear cuenta/tenant desde `http://localhost:5174`.
2. En la vista `Webhooks`, crear endpoint `whatsapp`.
3. Guardar el `verify_token_once` mostrado.
4. Enviar un evento de prueba:
   `Invoke-RestMethod -Method Post -Uri "http://localhost:8010/saas/v1/webhooks/whatsapp/<endpoint_key>" -Headers @{"x-scentra-webhook-token"="<verify_token_once>"} -ContentType "application/json" -Body '{"entry":[{"changes":[{"value":{"contacts":[{"wa_id":"573001112233","profile":{"name":"Cliente Demo"}}],"messages":[{"from":"573001112233","id":"wamid.demo.1","type":"text","text":{"body":"Hola, quiero informacion"}}]}}]}]}`
5. Procesar pendientes desde la vista `Webhooks` o esperar al worker.
6. Abrir `Inbox`.

## Firma HMAC opcional
1. Al crear un endpoint, activa `Requerir firma HMAC` si el emisor puede firmar el body.
2. La UI muestra `signature_secret_once` una sola vez.
3. La firma se envia en `x-scentra-signature-256` como `sha256=<hex_hmac_sha256_body>`.
4. Si `Requerir firma HMAC` esta apagado, el endpoint acepta `x-scentra-webhook-token` o firma valida.

## Prueba rapida de salida
1. Crea o actualiza una integracion con `channel=whatsapp` y `status=connected`.
2. Abre `Inbox`, selecciona una conversacion y escribe una respuesta.
3. El mensaje queda en `saas_outbound_messages` y el worker lo procesa como dispatch stub.

## Billing MVP local
1. Abre la vista `Billing`.
2. Revisa plan actual, limites y consumo del periodo.
3. Cambia entre `starter`, `growth` y `pro` con `Usar plan`.
4. Prueba limites:
   - `starter` permite 3 integraciones activas.
   - si se supera `max_integrations`, `POST /integrations` responde `402`.
   - si se supera `max_monthly_messages`, el envio desde `Inbox` responde `402`.

Nota: `POST /billing/dev/change-plan` solo funciona con `SAAS_ENV=local/dev`. En produccion el cambio de plan debe venir de Stripe Checkout/webhooks.

## Adaptador real Meta WhatsApp Cloud
El modo seguro por defecto es `stub`; registra el envio en la base sin contactar a Meta.

Para enviar mensajes reales:
1. Define el token en el entorno antes de levantar Docker:
   `$env:SCENTRA_META_ACCESS_TOKEN="<token_de_meta>"`
2. Reinicia API y worker:
   `docker compose -f docker-compose.saas.yml up -d --build api worker`
3. En `Integraciones`, guarda:
   - `Provider`: `meta`
   - `Channel`: `whatsapp`
   - `Status`: `connected`
   - `Modo`: `Meta Cloud real`
   - `Phone Number ID`: el ID del numero en Meta
   - `Token env var`: `SCENTRA_META_ACCESS_TOKEN`
4. En `Inbox`, envia una respuesta. El worker llamara a Graph API `/{phone_number_id}/messages`.

Notas:
- En SaaS real el cliente puede pegar su token permanente de Meta en `Ajustes > Canales`; el backend lo cifra y la UI solo muestra una pista.
- `SCENTRA_META_ACCESS_TOKEN` sigue funcionando como fallback global para pruebas o una sola cuenta de WhatsApp.
- `SCENTRA_META_GRAPH_VERSION` queda configurable para ajustar la version vigente de tu app Meta.
- Si falta token o `Phone Number ID`, el mensaje se marca como `failed` con el error correspondiente.
