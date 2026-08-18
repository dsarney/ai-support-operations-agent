---
id: kb-webhooks
title: Retrying failed outbound webhooks
category: integrations
component: webhooks
---

Northstar delivers `order.created`, `usage.updated`, and `member.invited` events to the workspace webhook URL. Delivery is retried automatically for 24 hours, then marked failed.

A workspace-level failure (TLS timeout, 5xx, invalid certificate) can be retried immediately with `retry_failed_webhook`. This does not change the URL. Platform-wide webhook degradation would appear on the status page instead.
