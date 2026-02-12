# Broker config schema

`~/.agentbox/broker/config.yaml` (host-owned, mounted read-only). See `config.example.yaml`
for a fully-commented working example - this file is a field reference, not a tutorial.

Reload: any hook call re-stats the file, throttled by `poll_interval`, and swaps in a freshly
parsed config on change - no restart. A parse error logs and keeps the previous good config.

## Top level

| Field | Type | Default | Description |
|---|---|---|---|
| `poll_interval` | float (seconds) | `1.0` | Minimum time between reload checks. |
| `deny_status` | int | `403` | HTTP status for a denied host. |
| `deny_message` | string | see example | Body for a denied host. `{host}` is interpolated. |
| `allowlist` | list of string | `[]` | Hosts the agent may reach. `fnmatch` globs (e.g. `*.github.io`). Anything unmatched is denied. |
| `tls_passthrough` | list of string | `[]` | Hosts tunnelled raw - never decrypted, never inspected, bypasses allow/deny and credential injection entirely. Same glob syntax. Should be a subset of `allowlist`; only list hosts that must never be MITM'd (Anthropic - see root README). |
| `credentials` | list of object | `[]` | Per-host credential injection. See below. |

Glob note: `*.anthropic.com` matches any subdomain, including `api.anthropic.com`, but not bare
`anthropic.com` - list both if you need both.

## `credentials[]`

| Field | Type | Required | Description |
|---|---|---|---|
| `host` | string | yes | Exact hostname (no globs - a wildcard credential host would risk leaking a secret to an unintended subdomain), matched against the actual request destination, not the spoofable `Host` header. Last entry wins if a host repeats. |
| `inject` | `header` \| `bearer` \| `basic` \| `query` | yes | `header`: sets header `name`. `bearer`: `Authorization: Bearer <value>`. `basic`: `Authorization: Basic base64(username:value)`. `query`: sets query param `name`. Overwrites anything the agent itself sent. |
| `name` | string | for `header`/`query` | Header or query parameter name. |
| `username` | string | for `basic` | Username half of the basic auth pair. |
| `value_env` | string | one of `value_env`/`value_file` | Env var read from the proxy's own environment (`secrets.env`, via `--env-file`). Captured at proxy startup - rotating it requires restarting the sidecar. |
| `value_file` | string | one of the two | Path inside the proxy container, re-read on every request - supports live secret rotation with no restart. |

`value_file` takes precedence if both are set.

## Out of scope (see root README / DEVELOPMENT_NOTES.md)

No per-branch/per-path credential scoping, no vault integration. The Anthropic OAuth token
(`~/.claude/.credentials.json`) is never brokered - it stays in the agent's persistent
`~/.claude` volume, by design.
