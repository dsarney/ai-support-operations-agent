---
id: kb-sso-okta
title: Set up SSO with Okta (SAML)
category: how_to
component: auth
---

Team and Enterprise plans can enable SAML SSO.

1. Open **Workspace settings → Security → SSO**.
2. Choose **Okta** and copy the ACS URL and Entity ID into an Okta SAML app.
3. Paste the IdP metadata URL back into Northstar and map email to `NameID`.
4. Turn on **Require SSO** only after a test login succeeds.

Starter plans must upgrade before SSO is available. Support should not configure a customer's Okta tenant for them.
