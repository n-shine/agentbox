You are running inside an AgentBox sandbox with network and credential brokering enabled
(`agentbox --broker`).

- Your outbound network traffic goes through a proxy sidecar, not directly to the internet. You
  cannot reach any host that is not on the broker's allowlist.
- You will not see and do not need most credentials (git/GitHub/GitLab tokens, registry tokens,
  cloud credentials). The proxy injects the real credential for allowlisted hosts transparently
  - send requests as normal (e.g. `git push`, `gh pr create`, `npm install`) without sourcing or
    exporting a token yourself.
- If a request fails with an error body starting "AgentBox egress broker: host '<host>' is not
  in the allowlist" (or you see a plain connection failure to a host you expected to reach): stop.
  This is not a transient failure - retrying, working around it, or trying a different tool will
  not help. Tell the human which host you need and why, and ask them to add it to
  `~/.agentbox/broker/config.yaml`. It reloads within seconds with no restart, so once they add
  it you can retry the same request.
- If a request fails with "credential for '<host>' is misconfigured", the broker has no working
  credential for that host - tell the human, do not try to supply your own token.
