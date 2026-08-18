---
id: kb-email-verification
title: Resending workspace verification email
category: access
component: auth
---

New workspaces must verify the admin email before mutating billing or inviting teammates. If the message is missing, check spam, then ask support to resend.

The `resend_verification_email` action queues a fresh message to the address on the customer record. It does not change the email itself. Verification links expire after 24 hours.
