# Deploying to Coolify

## Setup

1. **New Resource → Docker Compose**, pointed at this repository.
2. Coolify picks up `docker-compose.yml` at the repo root. Leave the compose
   file as-is; the build context is the repository itself.
3. **Set no environment secrets.** There are none to set — the server holds no
   Spotify credentials. `HOST` and `PORT` are already in the compose file and
   only need changing if 6402 clashes with something.
4. **Domain**: assign one to the `spotify-mcp-mx` service on port **6402**.
   Coolify's Traefik terminates TLS and proxies to the container.
5. **Health check**: path `/health`, port `6402`. The container also carries
   its own `HEALTHCHECK`, so Coolify will see the container report healthy
   either way. `/health` is deliberately unauthenticated.
6. Deploy, then verify:

   ```bash
   curl -sf https://your-domain/health
   ```

The MCP endpoint is then `https://your-domain/mcp`, with `/sse` available for
clients that still need the legacy transport.

## Why there are no secrets

Each caller sends their own Spotify `client_id`, `client_secret`, and
`refresh_token` in request headers on every request. The server builds a
client from those headers per tool call and drops it afterwards. Consequences
worth knowing:

- Rotating credentials is a client-side change; nothing here needs
  redeploying.
- The endpoint is **publicly reachable**. That is intended: a caller without
  valid Spotify credentials gets errors from Spotify, and no quota of yours is
  at risk because there is no credential of yours to spend. If you want the
  endpoint private anyway, put Coolify/Traefik basic-auth or an IP allowlist
  in front of it.
- Per-caller access-token caching is in-memory and derived from the headers
  supplied, so a redeploy costs each caller one extra token exchange and
  nothing else.

## Scaling and restarts

The server runs **stateless** Streamable HTTP: no MCP session is pinned to a
worker, because the caller's credentials travel on every request anyway.
Coolify can restart or scale the container without breaking connected
clients, and no sticky sessions are needed at the proxy.

## A note on Host header checks

The MCP SDK can enforce a DNS-rebinding allowlist on the `Host` and `Origin`
headers, and auto-enables it when told it is serving loopback. This
deployment binds `0.0.0.0`, so it stays off — with it on, requests arriving
through Traefik carrying your public domain in `Host` would be rejected. The
protection guards browser-based attacks on localhost-bound servers, which is
not this deployment's shape; the per-request credential requirement is what
gates actual use.

## Updating

Push to the tracked branch and redeploy. The Dockerfile installs dependencies
from `uv.lock` in a separate layer from the application code, so a code-only
change rebuilds in seconds.
