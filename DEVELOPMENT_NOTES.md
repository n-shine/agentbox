# AgentBox Development Notes (For Agents)

**Note**: Also read README.md for user-facing features, command usage, and Git authentication setup.

## Technical Context

### Project Origin
AgentBox is a simplified replacement for ClaudeBox. The user was maintaining patches to ClaudeBox but wanted to stop due to complexity. Key motivations:
- ClaudeBox has 1000+ users but too many features the user doesn't need
- Complex slot system and Bash 3.2 compatibility requirements made it hard to maintain
- Python profile in ClaudeBox was buggy
- User wanted automatic behavior without prompts

### Architecture Decisions

1. **Ephemeral Containers**: Containers use `--rm` flag and are destroyed on exit. This differs from ClaudeBox's persistent slot-based containers.

2. **Hash-Based Naming**: Container names use SHA256 hash of project directory path (first 12 chars) to ensure uniqueness and avoid conflicts.

3. **Bind Over Volume**: Claude CLI and OpenCode use bind mounts to host directories.

4. **SSH Implementation**: Currently mounts `~/.agentbox/ssh/` directory directly (not true SSH agent forwarding). Future improvement could use Docker's `--ssh` flag for better security.

5. **UID/GID Handling**: Dockerfile builds with host user's UID/GID passed as build args to minimize permission issues, but some remain (see ZSH history issue).

6. **Credential/Egress Broker (opt-in, `--broker`, Claude only)**: a stock `mitmproxy/mitmproxy` sidecar, addon bind-mounted (no custom image), sits between the agent and the network. Docker Compose (`broker/docker-compose.yml`) owns its lifecycle: the agent joins only a `--internal` network with no route out; the proxy is dual-homed and is the sole egress path - fail-closed for a non-root agent, no `NET_ADMIN`/iptables needed. The addon (`broker/broker_addon.py`) enforces an allow/deny host list, injects real credentials per destination host, and passes `tls_passthrough` hosts (Anthropic) through raw via mitmproxy's `tls_clienthello` hook, leaving the agent's own subscription session untouched (see point 7 for why). Config is a host-owned YAML file; every hook call opportunistically re-stats it (throttled by `poll_interval`) and swaps in a freshly parsed config on change - no restart, and a parse error keeps the last-good config rather than crashing or falling open.

7. **Anthropic OAuth token stays unbrokered**: Claude Code's own Bash tool runs as the same UID as the agent, so mounting the token but hiding it from the agent isn't possible - anything Claude can read to authenticate, the agent can read too. The only way to actually keep it off the agent is to keep it out of the container and have the broker inject it at the network edge instead. That's not just credential injection, though: the OAuth access token is short-lived (`.claude/.credentials.json` holds a `refreshToken` alongside it), so the broker would have to own Claude Code's own refresh flow - mint access tokens, inject the Bearer, persist the rotated refresh token - and become the sole holder of that refresh token to avoid rotation races with any other consumer. That's real complexity for one host, so it's deliberately not built: `~/.claude` is mounted as-is and Anthropic is passed through raw (see Future Improvement below).

## Implementation Details

### File Responsibilities
- `Dockerfile`: Multi-stage build with all language toolchains. Uses `USER agent` (UID 1000)
- `entrypoint.sh`: Minimal - only sets PATH and creates Python venvs. In broker mode, also trusts the proxy's CA (system store + per-tool env vars)
- `agentbox`: Main logic - rebuild detection, container lifecycle, mount management, and (opt-in) broker sidecar lifecycle
- `broker/docker-compose.yml`: sidecar + network lifecycle (stock mitmproxy image, addon bind-mounted, healthcheck-gated startup, `docker compose up`/`down`)
- `broker/broker_addon.py`: mitmproxy addon - allow/deny enforcement, credential injection, live config reload, Anthropic TLS passthrough
- `broker/config.example.yaml`, `broker/secrets.example.env`: scaffolded into `~/.agentbox/broker/` on first `--broker` run
- `broker/SCHEMA.md`: config field reference
- `broker/sandbox-guidance.md`: appended to Claude's system prompt in broker mode via `--append-system-prompt`, so the agent knows how to interpret a proxy denial

### Rebuild Detection
Automatic rebuilds are triggered by:
1. **File changes**: SHA256 hash of Dockerfile + entrypoint.sh stored as Docker image label. Compares on each run.
2. **Time-based**: If image is older than 48 hours, rebuild automatically to get latest tool versions (Claude Code/OpenCode).

This ensures tools stay updated without manual intervention or version checking overhead.

### Container Lifecycle
1. Check Docker daemon
2. Compare hashes → rebuild if needed (on rebuild: build new image, auto-prune dangling images)
3. Run ephemeral container with all mounts
4. Container removed automatically on exit

### Image Cleanup Strategy
After each successful rebuild, `docker image prune -f --filter "label=agentbox.version"` removes dangling agentbox images. This prevents accumulation over time without manual intervention.

### Mount Points
```bash
$PROJECT_DIR            # Project directory (mounted at full host path)
<additional_dirs>       # Additional directories via --add-dir (also mounted at full host paths)
/home/agent/.ssh        # SSH keys from ~/.agentbox/ssh/
/home/agent/.gitconfig  # Git config (read-only)
/home/agent/.npm        # NPM cache
/home/agent/.cache/pip  # Pip cache
/home/agent/.m2         # Maven cache
/home/agent/.gradle     # Gradle cache
/home/agent/.shell_history  # History directory (HISTFILE env var points to zsh_history inside)
/home/agent/.claude     # Claude config
/home/agent/.config/opencode  # OpenCode config
/home/agent/.local/share/opencode  # OpenCode auth
```

In `--broker` mode, `/home/agent/.ssh` and `.env` files are not mounted/loaded at all; instead
`/home/agent/.agentbox-ca` (the proxy's CA cert, read-only) is mounted and `HTTP(S)_PROXY` point
at the proxy sidecar. `/home/agent/.claude` is still mounted as-is (see Architecture Decisions).

## Testing Status
- Basic functionality verified (help command, shell mode)
- Full Docker build/run cycle needs real environment testing
- Multi-project isolation designed but not stress-tested
- SSH operations need testing with actual Git repositories

## Potential Future Improvements

1. **True SSH Agent Forwarding**: Replace key mounting with Docker's `--ssh` flag
2. **Build Cache Optimization**: Better layer ordering for faster rebuilds
3. **Permission Fixes**: Solve ZSH history permission issue properly
4. **Debug Mode**: Add verbose logging for troubleshooting
5. **Config File**: Support `.agentboxrc` for user preferences
6. **WSL2 Optimizations**: Specific handling for WSL2 environments
7. **Broker: hide the agent's own Anthropic token**: would need the broker to own the real OAuth token + refresh flow itself and become its sole holder, injecting a fresh access token at the network edge instead of the agent ever seeing one. Deliberately not built - see Architecture Decisions.
8. **Broker: devcontainer/IDE-native integration, multi-agent (`--tool`) support in broker mode, vault/1Password-backed credentials, git-branch-scoped credentials, per-project curated images** - explicitly out of scope for the initial broker; the config schema (`broker/SCHEMA.md`) and launcher flags are structured to make adding these straightforward later.

## Known Technical Issues

### Claude CLI Triple Display
- **Root Cause**: Ink framework's TTY handling in containers
- **Attempted Fixes**: Terminal size handling, TTY allocation modes
- **Status**: Unfixable without Claude CLI framework changes

### ZSH History Permissions
- **Root Cause**: Host file ownership (host UID) vs container user (UID 1000)
- **Attempted Fixes**: Various permission strategies, all had side effects
- **Status**: Cosmetic issue, functionality works

### Image Size
Current image is large (~2GB) due to multiple language toolchains. Could optimize with:
- Multi-stage builds with slimmer final stage
- Optional language support via build args
- Better layer caching strategies

## Development Philosophy

1. **Simplicity First**: Resist feature creep. The value is in being simpler than ClaudeBox.
2. **Automatic Behavior**: Users shouldn't need to think about container management.
3. **No Prompts**: Everything should work without user interaction (except initial SSH setup).
4. **Fail Gracefully**: Clear error messages, automatic recovery where possible.

## Command Analysis

The `agentbox` script has these key functions:
- `check_docker()`: Verify Docker daemon is running
- `calculate_hash()`: SHA256 hash for change detection
- `needs_rebuild()`: Compare hashes with image label
- `build_image()`: Docker build with proper args
- `mount_additional_dirs()`: Mount extra directories with intuitive folder names (e.g., /foo, /bar)
- `validate_dir_path()`: Validate directory paths (traversal check, system dirs, existence, duplicates)
- `run_container()`: Main container execution logic with all mounts and command execution
- `ssh_setup()`: Initialize ~/.agentbox/ssh/ directory

## Critical Implementation Notes

1. **Never use `-i` flag**: Git commands like `git rebase -i` won't work in non-interactive container context

2. **Path Hashing**: Container names use first 12 chars of SHA256(project_path) - collision risk is negligible

3. **Container Naming**: `agentbox-<hash>` pattern ensures per-project container isolation (separate caches and history, but shared tool authentication)

4. **Shell Mode**: When using `shell` command, execution goes through zsh even for bash (ensures environment is loaded)

5. **Admin Mode**: `--admin` flag doesn't actually grant sudo (would need Dockerfile changes) - currently just shows a message

## File Count
- Core files: 3 (Dockerfile, entrypoint.sh, agentbox)
- Documentation: 2 (README.md, DEVELOPMENT_NOTES.md)
- Other: .gitignore, LICENSE, CLAUDE.md
- Broker (opt-in, `--broker`): `broker/docker-compose.yml`, `broker/broker_addon.py`, `broker/config.example.yaml`, `broker/secrets.example.env`, `broker/SCHEMA.md`, `broker/sandbox-guidance.md`
- Total: ~8 files (vs ClaudeBox's 20+)
