"""AgentBox egress/credential broker: mitmproxy addon.

Sits between an agentbox agent container and the network. It:

  1. Enforces an allow/deny host list, returning a readable error body
     (not a hang) when a host is not allowlisted.
  2. Injects real credentials for hosts that have one configured, so the
     agent container never holds the underlying secret.
  3. Passes `tls_passthrough` hosts (Anthropic) straight through
     untouched, leaving the agent's own subscription session alone -
     see DEVELOPMENT_NOTES.md for why its OAuth token isn't brokered.

Config lives in a host-owned YAML file (mounted read-only). Every hook
call opportunistically re-stats it (throttled by `poll_interval`) and
swaps in a freshly parsed config on change, so editing hosts or
credentials on the host takes effect within a couple of seconds with no
proxy or container restart. A parse error keeps the last-good config
rather than crashing the proxy or falling open. See SCHEMA.md.
"""
import base64
import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from mitmproxy import ctx, http, tls

CONFIG_PATH = Path(os.environ.get("BROKER_CONFIG", "/config/config.yaml"))

DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_DENY_STATUS = 403
DEFAULT_DENY_MESSAGE = (
    "AgentBox egress broker: host '{host}' is not in the allowlist.\n"
    "Ask the human to add it to the broker config (reloads live, no restart needed).\n"
)

_yaml = YAML(typ="safe")


@dataclass
class Credential:
    host: str
    inject: str  # header | bearer | basic | query
    name: str | None = None
    username: str | None = None
    value_env: str | None = None
    value_file: str | None = None

    def resolve(self) -> str | None:
        # value_file is re-read live on every request; value_env is
        # captured from the proxy's own environment, which only changes
        # on container restart - see SCHEMA.md.
        if self.value_file:
            try:
                return Path(self.value_file).read_text().strip()
            except OSError as exc:
                ctx.log.warn(f"credential for {self.host}: cannot read value_file {self.value_file}: {exc}")
                return None
        if self.value_env:
            val = os.environ.get(self.value_env)
            if val is None:
                ctx.log.warn(f"credential for {self.host}: env var {self.value_env} is not set")
            return val
        ctx.log.warn(f"credential for {self.host}: no value_env/value_file configured")
        return None


@dataclass
class BrokerConfig:
    allowlist: list[str] = field(default_factory=list)
    tls_passthrough: list[str] = field(default_factory=list)
    credentials: dict[str, Credential] = field(default_factory=dict)
    poll_interval: float = DEFAULT_POLL_INTERVAL
    deny_status: int = DEFAULT_DENY_STATUS
    deny_message: str = DEFAULT_DENY_MESSAGE

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "BrokerConfig":
        credentials: dict[str, Credential] = {}
        for entry in raw.get("credentials") or []:
            cred = Credential(
                host=entry["host"],
                inject=entry["inject"],
                name=entry.get("name"),
                username=entry.get("username"),
                value_env=entry.get("value_env"),
                value_file=entry.get("value_file"),
            )
            # Credential hosts are matched exactly (no globs): a wildcard
            # credential host would risk leaking a secret to an
            # unintended subdomain. Last entry wins if a host repeats.
            credentials[cred.host.lower()] = cred
        return cls(
            allowlist=[h.lower() for h in (raw.get("allowlist") or [])],
            tls_passthrough=[h.lower() for h in (raw.get("tls_passthrough") or [])],
            credentials=credentials,
            poll_interval=float(raw.get("poll_interval", DEFAULT_POLL_INTERVAL)),
            deny_status=int(raw.get("deny_status", DEFAULT_DENY_STATUS)),
            deny_message=raw.get("deny_message", DEFAULT_DENY_MESSAGE),
        )


def _host_matches(host: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(host, pattern) for pattern in patterns)


class Broker:
    def __init__(self) -> None:
        self.config = BrokerConfig()  # fail closed: empty allowlist until first load
        self._mtime: float = 0.0
        self._last_check: float = 0.0

    def running(self) -> None:
        self._reload(force=True)

    def _maybe_reload(self) -> None:
        now = time.monotonic()
        if now - self._last_check < self.config.poll_interval:
            return
        self._last_check = now
        self._reload()

    def _reload(self, force: bool = False) -> None:
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except OSError as exc:
            if force:
                ctx.log.error(f"broker config {CONFIG_PATH} not readable: {exc} (denying all traffic)")
            return

        if not force and mtime == self._mtime:
            return

        try:
            raw = _yaml.load(CONFIG_PATH.read_text()) or {}
            new_config = BrokerConfig.parse(raw)
        except Exception as exc:  # noqa: BLE001 - a bad edit must never crash the proxy
            ctx.log.error(f"broker config reload failed, keeping previous config: {exc}")
            return

        self.config = new_config
        self._mtime = mtime
        ctx.log.info(
            f"broker config (re)loaded: {len(new_config.allowlist)} allowlist entries, "
            f"{len(new_config.tls_passthrough)} passthrough, {len(new_config.credentials)} credentials"
        )

    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        self._maybe_reload()
        sni = data.client_hello.sni
        if sni and _host_matches(sni.lower(), self.config.tls_passthrough):
            data.ignore_connection = True

    def _deny(self, flow: http.HTTPFlow, host: str) -> None:
        config = self.config
        body = config.deny_message.format(host=host)
        flow.response = http.Response.make(
            config.deny_status,
            body.encode(),
            {"Content-Type": "text/plain", "X-AgentBox-Broker": "denied"},
        )
        ctx.log.warn(f"denied request to {host}")

    def request(self, flow: http.HTTPFlow) -> None:
        self._maybe_reload()

        # `.host` is the actual CONNECT/TLS destination, not the
        # (spoofable) Host header - do not use `.pretty_host` here, or a
        # forged Host header could bypass the allowlist or redirect an
        # injected credential to an unintended destination.
        host = flow.request.host.lower()
        config = self.config

        if not _host_matches(host, config.allowlist):
            self._deny(flow, host)
            return

        cred = config.credentials.get(host)
        if cred is None:
            return

        value = cred.resolve()
        if value is None:
            flow.response = http.Response.make(
                502,
                (
                    f"AgentBox egress broker: credential for '{host}' is misconfigured. "
                    "Check broker secrets and proxy logs.\n"
                ).encode(),
                {"Content-Type": "text/plain", "X-AgentBox-Broker": "cred-error"},
            )
            return

        if cred.inject == "header":
            flow.request.headers[cred.name] = value
        elif cred.inject == "bearer":
            flow.request.headers["Authorization"] = f"Bearer {value}"
        elif cred.inject == "basic":
            token = base64.b64encode(f"{cred.username or ''}:{value}".encode()).decode()
            flow.request.headers["Authorization"] = f"Basic {token}"
        elif cred.inject == "query":
            flow.request.query[cred.name] = value
        else:
            ctx.log.warn(f"credential for {host}: unknown inject type {cred.inject!r}")


addons = [Broker()]
