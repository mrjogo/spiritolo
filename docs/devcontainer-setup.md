<!-- [repo-mixin:devcontainer-claude] Devcontainer + Claude Code setup documentation.
     Explains the startup lifecycle, why each piece exists, and troubleshooting. -->

# Devcontainer + Claude Code Setup

## Startup Lifecycle

```
1. initializeCommand/       HOST      — captures host paths, GH token, SSH agent
2. Dockerfile               build     — installs tmux, Claude Code, .inputrc
3. devcontainer.json         start     — mounts ~/.claude, sets env
4. postCreateCommand/        container — bridges Claude Code paths
```

Lifecycle hooks use the devcontainer **object format** — each mixin adds a named entry to the hook, and the runtime runs them in parallel. Scripts live in directories named after their hook (`initializeCommand/`, `postCreateCommand/`).

## Why Each Piece Exists

### initializeCommand/capture-claude-env.sh (host)

Writes `.devcontainer/.env.devcontainer` (gitignored) with:
- `HOST_PROJECT_DIR` — needed because Claude Code keys history by absolute path, and the host path differs from the container path
- `GH_TOKEN` — forwarded from `gh auth token` so `gh` works inside the container without re-auth

Creates a stable symlink named `devcontainer-ssh-agent.sock` pointing to the SSH agent socket. On macOS, the symlink is created inside Docker Desktop's LinuxKit VM at `/run/` (pointing to the VM's SSH agent relay). On Linux, it's created in `$XDG_RUNTIME_DIR` (pointing to `$SSH_AUTH_SOCK`). The devcontainer.json mount source uses `${localEnv:XDG_RUNTIME_DIR:/run}` to resolve the right path per platform.

### Dockerfile

- **tmux** — run Claude Code in a tmux session so it survives IDE disconnects
- **Claude Code** — standalone installer to `~/.local/bin`
- **.inputrc** — arrow-key prefix history search

### devcontainer.json

- Mounts `~/.claude` (shared config/history/plugins) and the host SSH agent socket (via the stable symlink)
- Sets `CLAUDE_CONFIG_DIR`, `HOST_HOME`, `SSH_AUTH_SOCK`, and `PATH`
- Installs GitHub CLI and the Claude Code VS Code extension

### postCreateCommand/setup-claude-code.sh (container)

Solves two host/container path mismatches:

**Project history:** Claude stores history at `~/.claude/projects/-Users-you-projects-myapp`. Inside the container the project is at `/workspaces/myapp`, so Claude would look for `-workspaces-myapp`. The script symlinks the container path to the host path's history directory.

**Plugin paths:** Plugins reference the host home (e.g., `/Users/you/.claude/plugins/...`). The script symlinks `$HOST_HOME/.claude` to the container's `~/.claude` so those paths resolve.

## Settings Management

`.claude/settings.json` — pre-allowed safe commands (ls, grep, git read-only, etc.). Add to this as you work.

`.claude/manage_settings.py` — sorts and merges permissions:

```bash
python .claude/manage_settings.py                              # sort in place
python .claude/manage_settings.py --dry-run                    # preview
python .claude/manage_settings.py --merge other/settings.json  # merge + sort
```

## Devcontainer CLI

The [`devcontainer` CLI](https://github.com/devcontainers/cli) lets you build, start, and interact with devcontainers without opening VS Code. Install it with:

```bash
npm install -g @devcontainers/cli
```

### Build and start the container

```bash
devcontainer up --workspace-folder . --remove-existing-container
```

Starts the container and runs `initializeCommand` entries (e.g., `capture-claude-env.sh`). This does **not** reliably run lifecycle commands like `postCreateCommand`.

### Run lifecycle commands

```bash
devcontainer run-user-commands --workspace-folder .
```

Runs `postCreateCommand` (and other lifecycle hooks) after `up`. This is what triggers `setup-claude-code.sh`. You must run this after `up` — the CLI does not run these automatically.

### Open a shell

```bash
devcontainer exec --workspace-folder . bash
```

Drops you into a bash shell inside the running container. Useful for verifying tools are installed:

```bash
devcontainer exec --workspace-folder . bash -c "which claude && which gh && tmux -V"
```

### Full test sequence

```bash
devcontainer build --workspace-folder .
devcontainer up --workspace-folder .
devcontainer run-user-commands --workspace-folder .
devcontainer exec --workspace-folder . bash
```

## Troubleshooting

- **No conversation history:** check `.devcontainer/.env.devcontainer` exists and contains `HOST_PROJECT_DIR`
- **"exists as a real directory" error:** remove the directory manually as the error suggests, rebuild
- **`gh` fails:** run `gh auth login` on host before starting container
- **Claude Code not found:** check `~/.local/bin` is on PATH
