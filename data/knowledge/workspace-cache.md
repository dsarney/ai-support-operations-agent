---
id: kb-workspace-cache
title: Stale dashboards and workspace cache
category: performance
component: cache
---

Usage and billing widgets are cached per workspace for a few minutes. If a customer sees yesterday's numbers after a refresh, the workspace cache may be stale.

The `clear_workspace_cache` action drops that tenant's cached views. It does not restart shared infrastructure and is safe on all plans.
