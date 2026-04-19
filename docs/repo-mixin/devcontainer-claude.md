# devcontainer-claude mixin

Applied from: https://github.com/mrjogo/repo-mixin/tree/main/mixins/devcontainer-claude
Applied commit: 0b97f52ad7efad619bee341ff2d83f0a24a46fc4
Applied: 2026-04-18

## What this does

Sets up a devcontainer with Claude Code integration, including conversation
history bridging between host and container, tmux for session persistence,
GitHub CLI with auth forwarding, starter Claude Code permissions, and an
optional macOS notification hook.

## Files touched

- .devcontainer/Dockerfile
- .devcontainer/devcontainer.json
- .devcontainer/.inputrc
- .devcontainer/initializeCommand/capture-claude-env.sh
- .devcontainer/postCreateCommand/setup-claude-code.sh
- .devcontainer/host-claude-notifications/README.md
- .devcontainer/host-claude-notifications/local.claude-notify-listener.plist
- .devcontainer/host-claude-notifications/notify-listen.py
- .claude/settings.json
- .claude/settings.json.repo-mixin.jsonc
- .claude/manage_settings.py
- .claude/hooks/notify.sh
- .gitignore
- CLAUDE.md
- docs/devcontainer-setup.md

## Composability patterns

- **Post-create hooks**: `postCreateCommand` in devcontainer.json uses object format. Each mixin adds a named entry. Scripts live in `.devcontainer/postCreateCommand/`.
- **Initialize hooks**: `initializeCommand` in devcontainer.json uses object format. Scripts live in `.devcontainer/initializeCommand/`.
- **.gitignore**: marked sections with `# --- repo-mixin:<name> ---` delimiters. Add entries within your mixin's markers.
- **Dockerfile**: annotated blocks with `[repo-mixin:<name>]`. Add your mixin's blocks with annotations.
