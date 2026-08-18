---
id: kb-account-lockout
title: Account lockouts and failed sign-in attempts
category: access
component: auth
---

Northstar Cloud locks a user after several consecutive failed password attempts. The lock is workspace-scoped for that identity, not a platform outage.

Support can safely unlock the account with the `unlock_account` action after confirming the requester owns the mailbox. Unlocking does not reset the password.

Customers should then sign in and, if they still cannot, use the password reset flow from the login page. SSO-managed users must be unlocked in the identity provider as well.
