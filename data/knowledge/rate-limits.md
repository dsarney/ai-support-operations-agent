---
id: kb-rate-limits
title: API rate limits by plan
category: how_to
component: api-gateway
---

Northstar applies per-token rate limits:

| Plan       | Requests / minute | Burst |
| ---------- | ----------------- | ----- |
| Starter    | 60                | 120   |
| Team       | 300               | 600   |
| Enterprise | 1,200             | 2,400 |

Throttled responses are `429` with `Retry-After` and `X-RateLimit-Remaining`. Burst is not a daily quota. Persistent 502/503 from the API gateway is an incident, not a rate-limit event.
