![AgentBox Logo](media/logo-image-only-150.png)

# AgentBox

A Docker-based development environment for running agentic coding tools in a more safe, isolated fashion. This makes it less dangerous to give your agent full permissions (YOLO mode / `--dangerously-skip-permissions`), which is, in my opinion, the only way to use AI agents.

## Features

- **Shares project directory with host**: Maps a volume with the source code so that you can see and modify the agent's changes on the host machine - just like if you were running your tool without a container.
- **Multi-Tool Support**: All agentic coding tools are supported, some built-in, others [via prompt](#adding-tools).
- **Unified Development Environment**: Single Docker image with Python, Node.js, Java, and Shell support
- **Isolated SSH**: Dedicated SSH directory for secure Git operations
- **Credential & Egress Broker** (opt-in, `--broker`, Claude only): routes all outbound traffic through an allow/deny + credential-injection proxy sidecar, so SSH keys, Git/GitHub tokens, and other secrets never touch the agent container. See [Credential & Egress Broker](#credential--egress-broker---broker).
- **Low-Maintenance Philosophy**: Always uses latest LTS tool versions, rebuilds container automatically when necessary

## Requirements

- **Docker**: Must be installed and running
- **Bash 4.0+**: macOS ships with Bash 3.2, I recommend upgrading via Homebrew (`brew install bash`).

## Installation and Quick Start

1. Clone AgentBox to your preferred location (e.g. `~/code/agentbox/agentbox`)
2. Ensure Docker is installed and running
3. Make the script executable: `chmod +x agentbox`
4. (Strongly recommended) add an alias for global access - e.g. alias `agentbox` to `~/code/agentbox/agentbox`.
5. Run `agentbox` from your desired working directory (wherever you would normally start your agentic coding tool).

## CLI Agent Support

- claude code: built-in
- opencode: built-in
- any other agents (copilot CLI, Aider, Cursor CLI...): easily add it yourself using the prompt at [docs/prompts/add-tool.md](docs/prompts/add-tool.md).

### Adding tools

Start your coding agent in the agentbox directory and issue this (example) prompt:
> Add support for Copilot CLI to this project using the instructions at @docs/prompts/add-tool.md.

Then you can go to your project directory and run (e.g.) `agentbox --tool copilot`. Thanks to [Felix Medam](https://github.com/SputnikTea) for this very cool idea.

## Helpful Commands

```bash
# Start Claude CLI in container (--dangerously-skip-permissions is automatically included)
agentbox

# Use OpenCode instead of Claude
agentbox --tool opencode

# Or set via environment variable
AGENTBOX_TOOL=opencode agentbox

# Show available commands
agentbox --help

# Non-agentbox CLI flags are passed through to claude.
# For example, to continue the most recent session
agentbox -c

# Mount additional directories for multi-project access
agentbox --add-dir ~/proj1 --add-dir ~/proj2

# Start shell with sudo privileges
agentbox shell --admin

# Set up SSH keys for AgentBox
agentbox ssh-init

# Route egress through the credential/network broker (no SSH/token mounts)
agentbox --broker

# Brokered session, pick up from your phone/browser/VS Code
agentbox --broker --remote-control
```

**Note**: Tool selection via `--tool` flag takes precedence over the `AGENTBOX_TOOL` environment variable.

## How It Works

AgentBox creates ephemeral Docker containers (with `--rm`) that are automatically removed when you exit. However, important data persists between sessions:

```
Single Dockerfile → Build once → agentbox:latest image
                                         ↓
                    ┌────────────────────┼────────────────────┐
                    ↓                    ↓                    ↓
          Container: project1    Container: project2    Container: project3
          (ephemeral, --rm)      (ephemeral, --rm)      (ephemeral, --rm)
          Mounts: ~/code/api    Mounts: ~/code/web     Mounts: ~/code/cli

Persistent data (survives container removal):
  Cache: ~/.cache/agentbox/agentbox-<hash>/
  History: ~/.agentbox/projects/agentbox-<hash>/history/
  Claude: ~/.claude
  OpenCode: ~/.config/opencode and ~/.local/share/opencode
```

## Languages and Tools

The unified Docker image includes:

- **Python**: Latest version with `uv` for fast package management
- **Node.js**: Latest LTS via NVM with npm, yarn, and pnpm
- **Java**: Latest LTS via SDKMAN with Gradle
- **Shell**: Zsh (default) and Bash with common utilities
- **Claude CLI**: Pre-installed with per-project authentication
- **OpenCode**: Pre-installed as an alternative AI coding tool

## Authenticating to Git or other SCC Providers

### GitHub
The `gh` tool is included in the image and can be used for all GitHub operations. My recommendation:
- Visit this link to configure a [fine-grained access-token](https://github.com/settings/personal-access-tokens/new?name=MyRepo-AI&description=For%20AI%20Agent%20Usage&contents=write&pull_requests=write&issues=write) with a sensible set of permissions predefined.
- On that page, restrict the token to the project repository.
- Create a .env file at the root of your project repository with entry `GH_TOKEN=<token>`
- Add some instructions to the CLAUDE.md file, telling it to use the `gh` tool for Git operations. You can see a slightly more complicated example in this repo, there is a sub-agent for git operations in .claude/agents and instructions in CLAUDE.md to remember to use agents.

You or your agent should convert ssh git remotes to https, ssh remotes don't work with tokens.

### GitLab
 The `glab` tool is included in the image. You can use it with a GitLab token for API operations, but not for git operations as far as I know. So for GitLab I recommend the SSH configuration detailed below.

## Git Configuration

AgentBox copies your host `~/.gitconfig` into the container on each startup. If you don't have a host gitconfig, it uses `agent@agentbox` as the default identity.

## SSH Configuration

AgentBox uses a dedicated SSH directory (`~/.agentbox/ssh/`) isolated from your main SSH keys:

```bash
# Initialize SSH for AgentBox
agentbox ssh-init
```

This will:
1. Create ~/.agentbox/ssh/ directory
2. Copy your known_hosts for host verification
3. Generate a new Ed25519 key pair (if preferred, delete them and manually place your desired SSH keys in `~/.agentbox/ssh/`).

### Environment Variables
Environment variables are loaded from `.env` files in this order (later overrides earlier):
1. `~/.agentbox/.env` (global)
2. `<project-dir>/.env` (project-specific)

AgentBox includes `direnv` support - `.envrc` files are evaluated if `direnv allow`ed on the host.

## Remote Control (`--remote-control`)

`--remote-control` is a standard Claude Code flag, passed through like any other (see Helpful Commands above) - agentbox has no dedicated flag for it. It starts Claude Code with [Remote Control](https://code.claude.com/docs/en/remote-control) enabled, so you can pick up the running session from claude.ai/code, the Claude mobile app, or the VS Code extension. Requires `--tool claude` (the default) and a claude.ai OAuth login (API key auth is not supported by Remote Control).

```bash
agentbox --remote-control
```

**Caveat**: agentbox always runs Claude Code with `--dangerously-skip-permissions`. Combined with `--remote-control`, this means anyone with access to the session from your phone, browser, or IDE can drive unrestricted command execution in the container with no permission prompts - the remote surface has exactly the same power as your local terminal. Only use it on an account/device you trust, and be aware the session transcript is stored on Anthropic's servers while Remote Control is connected (see their [data usage policy](https://code.claude.com/docs/en/data-usage)).

## Credential & Egress Broker (`--broker`)

By default AgentBox mounts your SSH keys, `.gitconfig`, and `.env` tokens straight into the agent
- all visible to a YOLO-mode agent with full Bash access. `--broker` (Claude only) puts a proxy
sidecar between the agent and the network instead: the agent joins a Docker `--internal` network
with no route out except through the proxy (no SSH keys or `.env` files mounted), the proxy enforces
an allow/deny host list (a denied host gets a clear error body the agent can act on, not a hang),
and injects real credentials into requests for hosts you've configured - the agent never holds the
secret.

```bash
agentbox --broker
```

First run scaffolds `~/.agentbox/broker/config.yaml` (allowlist/credentials - see
[broker/SCHEMA.md](broker/SCHEMA.md) and [broker/config.example.yaml](broker/config.example.yaml))
and `secrets.env` (mode 600, actual token values). Edit both, then run `agentbox --broker` again.

Saved changes to `config.yaml` take effect within a couple of seconds, no restart - except a value
changed in `secrets.env` itself, which needs a restart since it's read into the proxy's environment
once at startup (use `value_file` instead of `value_env` for live rotation).

The Anthropic OAuth token (`~/.claude/.credentials.json`) is **not** brokered - it stays mounted as
in non-broker mode. Claude Code's own Bash tool runs as the same UID as the agent, so there's no way
to hide the tool's own credentials from itself; the only real fix is keeping the token out of the
container and having the broker inject it instead. But the access token is short-lived and paired
with a refresh token, so that means the broker owning Claude Code's own OAuth refresh flow, not just
injecting a static value - not built. Everything else (Git/GitHub/GitLab tokens, cloud credentials,
registry tokens, SSH keys) is brokered.

Claude only (no `--tool opencode`), one broker per project at a time. No devcontainer integration,
vault/1Password integration, or per-branch credential scoping - the config format is structured to
make adding these straightforward later, but none of it is built.

## MCP Server Configuration

Due to [Claude Code bug #6130](https://github.com/anthropics/claude-code/issues/6130), by default you won't be prompted to enable MCP servers when running `agentbox` directly.

**Workaround options:**

1. **Enable individual MCP servers interactively:**
   ```bash
   agentbox shell
   claude
   ```

2. **Enable all MCP servers by default** by adding `"enableAllProjectMcpServers": true` to your Claude project or user settings.

## Data Persistence

### Package Caches
Package manager caches are stored in `~/.cache/agentbox/<container-name>/`:
- npm packages: `~/.cache/agentbox/<container-name>/npm`
- pip packages: `~/.cache/agentbox/<container-name>/pip`
- Maven artifacts: `~/.cache/agentbox/<container-name>/maven`
- Gradle cache: `~/.cache/agentbox/<container-name>/gradle`

### Shell History
Zsh history is preserved in `~/.agentbox/projects/<container-name>/history`

### Tool Authentication

Both tools use bind mounts to share authentication across all AgentBox projects:

**Claude CLI**:
- `~/.claude` mounted at `/home/agent/.claude`

**OpenCode**:
- Config: `~/.config/opencode` mounted at `/home/agent/.config/opencode`
- Auth: `~/.local/share/opencode` mounted at `/home/agent/.local/share/opencode`

### Broker State (`--broker` mode)

`~/.agentbox/broker/` holds the broker's host-owned state, shared across all projects run with `--broker`:
- `config.yaml` - allowlist/credentials config, edited live (see [Credential & Egress Broker](#credential--egress-broker---broker))
- `secrets.env` - actual secret values (mode 600)
- `ca/` - the proxy's MITM CA certificate, generated on first run and reused across projects

## Advanced Usage

### Running One-Off Commands
If you need to run a single command in the containerized environment without starting Claude CLI or an interactive shell:

```bash
# Run any command
agentbox npm test
```

### Rebuild Control
```bash
# Force rebuild the Docker image
agentbox --rebuild
```

The image automatically rebuilds when:
- Dockerfile or entrypoint.sh changes
- Image is older than 48 hours (to get latest tool versions)

## Tool / Dependency Versions
The Dockerfile is configured to pull the latest stable version of each tool (NVM, GitLab CLI, etc.) during the build process. This makes maintenance easy and ensures that we always use current software. It also means that rebuilding the Docker image may automatically result in newer versions of tools being installed, which could introduce unexpected behavior or breaking changes. If you require specific tool versions, consider pinning them in the Dockerfile.

## Alternatives
### Anthropic DevContainer
Anthropic offers a [devcontainer](https://github.com/anthropics/claude-code/tree/main/.devcontainer) which achieves a similar goal. If you like devcontainers, that's a good option. Unfortunately, I find that devcontainers sometimes have weird bugs, problematic support in IntelliJ/Mac, or they are just more cumbersome to use (try switching to a recent project with a shortcut, for example). I don't want to force people to use a devcontainer if what they really want is safe YOLO-mode isolation - the simpler solution to the problem is just Docker, hence, this project.

### Comparison with ClaudeBox
AgentBox began as a simplified replacement for [ClaudeBox](https://github.com/RchGrav/claudebox). I liked the ClaudeBox project, but its complexity caused a lot of bugs and I found myself maintaning my own fork with my not-yet-merged PRs. It became easier for me to build something leaner for my own needs. Comparison:

| Feature | AgentBox | ClaudeBox |
|---------|----------|-----------|
| Files | 3 core files | 20+ files |
| Profiles | Single unified image | 20+ language profiles |
| Container Management | Simple per-project | Advanced slot system |
| Setup | Automatic | Manual configuration |

## Support and Contributing
I make no guarantee to support this project in the future, however the history is positive: I've actively supported it since September 2025. Feel free to create issues and submit PRs. The project is designed to be understandable enough that if you need specific custom changes which we don't want centrally, you can fork or just make them locally for yourself.

If you do contribute, consider that AgentBox is designed to be simple and maintainable. The value of new features will always be weighed against the added complexity. Try to find the simplest possible way to get things done and control the AI's desire to write such bloated doco.
