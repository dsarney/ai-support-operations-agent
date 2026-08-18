---
id: kb-api-gateway-errors
title: API gateway 502 and 503 errors
category: outage
component: api-gateway
---

`502` and `503` from `api.northstar.example` mean the edge cannot reach a healthy origin. This is not a customer API-key problem.

If **API Gateway** is degraded on the status board, correlate tickets instead of applying workspace remediations. Do not rotate keys, unlock accounts, or retry webhooks as a fix for platform 5xx. Escalate so humans can own customer comms.
