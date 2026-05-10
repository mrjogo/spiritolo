<!-- [repo-mixin:devcontainer-claude] Devcontainer + Claude Code setup documentation.
     Explains the startup lifecycle, why each piece exists, and troubleshooting. -->

# Devcontainer + Claude Code Setup

## Startup Lifecycle

```
1. initializeCommand/       HOST      — sets up SSH agent socket symlink
2. Dockerfile               build     — installs tmux, Claude Code, .inputrc
3. devcontainer.json         start     — mounts ~/.claude, sets env (incl. HOST_HOME, HOST_PROJECT_DIR, GH_TOKEN)
4. postCreateCommand/        container — bridges Claude Code paths
```

Lifecycle hooks use the devcontainer **object format** — each mixin adds a named entry to the hook, and the runtime runs them in parallel. Scripts live in directories named after their hook (`initializeCommand/`, `postCreateCommand/`).

## Why Each Piece Exists

### initializeCommand/capture-claude-env.sh (host)

Creates a stable symlink named `devcontainer-ssh-agent.sock` pointing to the SSH agent socket. On macOS, the symlink is created inside Docker Desktop's LinuxKit VM at `/run/` (pointing to the VM's SSH agent relay). On Linux, it's created in `$XDG_RUNTIME_DIR` (pointing to `$SSH_AUTH_SOCK`). The devcontainer.json mount source uses `${localEnv:XDG_RUNTIME_DIR:/run}` to resolve the right path per platform.

`HOST_HOME`, `HOST_PROJECT_DIR`, and `GH_TOKEN` are passed via `containerEnv` in `devcontainer.json` using `${localEnv:HOME}`, `${localWorkspaceFolder}`, and `${localEnv:GH_TOKEN}` — not via this script — so they work even in runtimes (like DevPod) that don't reliably honor `initializeCommand` before container creation.

`GH_TOKEN` requires the host shell to export it. See "Host shell setup" below.

### Dockerfile

- **tmux** — run Claude Code in a tmux session so it survives IDE disconnects
- **Claude Code** — standalone installer to `~/.local/bin`
- **.inputrc** — arrow-key prefix history search

### devcontainer.json

- Mounts `~/.claude` (shared config/history/plugins) and the host SSH agent socket (via the stable symlink)
- Sets `CLAUDE_CONFIG_DIR`, `HOST_HOME`, `HOST_PROJECT_DIR`, `GH_TOKEN`, `SSH_AUTH_SOCK`, `CLAUDE_NOTIFY_HOST`, and `PATH`
- Installs GitHub CLI and the Claude Code VS Code extension

### postCreateCommand/setup-claude-code.sh (container)

Solves two host/container path mismatches:

**Project history:** Claude stores history at `~/.claude/projects/-Users-you-projects-myapp`. Inside the container the project is at `/workspaces/myapp`, so Claude would look for `-workspaces-myapp`. The script symlinks the container path to the host path's history directory.

**Plugin paths:** Plugins reference the host home (e.g., `/Users/you/.claude/plugins/...`). The script symlinks `$HOST_HOME/.claude` to the container's `~/.claude` so those paths resolve.

## Host shell setup

`GH_TOKEN` is passed into the container via `${localEnv:GH_TOKEN}` in `containerEnv`. The host shell that launches the container (whether VS Code, the `devcontainer` CLI, or DevPod) must already have it exported.

**macOS / Linux (interactive shells):** add to `~/.zshrc` or `~/.bashrc`:

```bash
export GH_TOKEN="$(gh auth token)"
```

**macOS (GUI-launched VS Code):** GUI apps don't read `~/.zshrc`. Use `launchctl setenv` so VS Code (and any other GUI launcher) sees it:

```bash
launchctl setenv GH_TOKEN "$(gh auth token)"
```

Add this to a login script (e.g., `~/.zprofile`) to persist it across reboots. Note that `launchctl setenv` makes the value visible to every GUI process — fine for a personal machine, less so for shared workstations.

If `GH_TOKEN` is unset on the host, `${localEnv:GH_TOKEN}` resolves to an empty string. `gh` inside the container will fall back to its normal config-file lookup; if there is none, it'll fail with an auth error.

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

## Notifications (Optional)

Native macOS notifications when Claude Code needs attention. See `.devcontainer/host-claude-notifications/README.md` for host-side install instructions.

In devcontainers, the `CLAUDE_NOTIFY_HOST` env var is set to `host.docker.internal` so the notification hook reaches the host's listener directly — no bridge process needed.

## Troubleshooting

- **No conversation history:** check `HOST_PROJECT_DIR` is set inside the container (`echo $HOST_PROJECT_DIR`); it should equal the host-side absolute path of the workspace folder
- **"exists as a real directory" error:** remove the directory manually as the error suggests, rebuild
- **`gh` fails:** ensure `GH_TOKEN` is exported on the host (e.g., via `.zshrc` or `launchctl setenv`); the container reads it via `${localEnv:GH_TOKEN}` in `containerEnv`. See "Host shell setup".
- **Claude Code not found:** check `~/.local/bin` is on PATH
