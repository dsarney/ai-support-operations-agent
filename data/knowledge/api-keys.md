---
id: kb-api-keys
title: Rotating a workspace API key
category: access
component: auth
---

Each workspace has one live secret key (`nsk_live_...`). If it is leaked, committed, or held by a departing contractor, rotate it.

The `rotate_workspace_api_key` action issues a new secret and invalidates the previous one immediately. Integrations must be updated before they will authenticate again. Never paste the full secret into a ticket reply.
