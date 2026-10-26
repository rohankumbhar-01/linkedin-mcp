# LinkedIn MCP

An approval-first Model Context Protocol (MCP) server for authorized LinkedIn workflows. It supports OAuth token exchange, basic OpenID profile retrieval, profile rewrite planning, post drafts, and explicit-approval publishing through LinkedIn's official Posts API.

> **API limitation:** LinkedIn does not generally allow ordinary developer apps to edit a member's headline, About, experience, or skills directly. Those features are draft-and-review workflows unless LinkedIn grants a supported API capability. Access to products and scopes is controlled by LinkedIn.

## Features

- MCP tools usable by compatible LLM clients.
- OAuth 2.0 authorization-code flow; secrets are read from environment variables.
- Basic member profile fields through OpenID Connect `userinfo`.
- Profile restructuring proposals without pretending to write unsupported fields.
- Post drafting and explicit-approval publishing through the official API.
- No browser scraping, password collection, or session-cookie automation.

## Quick start

Requirements: Python 3.11+, a LinkedIn developer app, and access to the products/scopes required for your intended operations.

```bash
git clone https://github.com/rohankumbhar-01/linkedin-mcp.git
cd linkedin-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and `LINKEDIN_REDIRECT_URI` in `.env`. Add the exact redirect URI in the LinkedIn Developer Portal. Do not commit `.env` or token files.

Run locally:

```bash
linkedin-mcp
```

The default transport is `stdio`, suitable for local MCP clients. The server also supports `MCP_TRANSPORT=streamable-http`, but do **not** expose it publicly until authentication, TLS, and network access controls have been configured. A public MCP endpoint needs its own client authentication and authorization layer; LinkedIn OAuth alone does not protect the MCP endpoint.

## OAuth flow

1. Call `linkedin_start_oauth`.
2. Open the returned authorization URL and approve the permissions.
3. The redirect URL includes `code` and `state`. Pass both to `linkedin_exchange_code` in the same running server session.
4. Call `linkedin_connection_status` and `linkedin_get_my_profile`.

The configured redirect URI must exactly match the LinkedIn developer app setting. Requested scopes only work if the app has the relevant product access. The token is stored in `~/.linkedin-mcp/token.json` with owner-only permissions where supported. For production, use a managed secret store or encrypted token storage and add refresh/revocation handling.

## MCP tools

| Tool | Purpose |
|---|---|
| `linkedin_connection_status` | Check token status without revealing it |
| `linkedin_start_oauth` | Generate authorization URL and CSRF state |
| `linkedin_exchange_code` | Exchange the code and store token |
| `linkedin_get_my_profile` | Read basic OpenID profile data |
| `linkedin_draft_profile_changes` | Prepare profile rewrite instructions; no writes |
| `linkedin_prepare_post` | Prepare a post draft |
| `linkedin_publish_approved_post` | Publish only when `approved=true` |
| `linkedin_capabilities_and_limits` | Report implemented capabilities and API limitations |

## LinkedIn API access

- OAuth: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
- OpenID Connect: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
- Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- API terms: https://developer.linkedin.com/legal

Before production use, confirm the current supported `LINKEDIN_API_VERSION`, endpoint payload requirements, and app permissions against the official documentation. API access can vary by app/product approval.

## Security checklist before remote hosting

- Add authentication for MCP clients; never expose an unauthenticated public MCP endpoint.
- Use HTTPS and a reverse proxy with strict access controls.
- Store client secrets and tokens in a secret manager or encrypted store.
- Implement token refresh/revocation and OAuth callback handling appropriate for the deployment.
- Add audit logging without logging secrets or full tokens.
- Keep publishing approval explicit and show the exact text before publishing.
- Add tests and CI before using this with a real LinkedIn account.

## Current scope and limitations

This is an initial implementation, not a promise that every LinkedIn action is available. It does not scrape LinkedIn pages or bypass access restrictions. Direct edits to headline, About, work experience, and skills are not implemented because those write operations are not generally available through standard member APIs. The initial OAuth exchange expects the authorization code and state to be submitted manually to the MCP tool; a production deployment should add a dedicated callback flow and state/session persistence.

## License

MIT
