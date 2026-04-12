# devcontainer-claude mixin

Applied from: https://github.com/mrjogo/repo-mixin/tree/main/mixins/devcontainer-claude
Applied commit: 3083239f2c1d927e39457d15bb1c8df4840f047c
Applied: 2026-04-12

## What this does

Sets up a devcontainer with Claude Code integration, including conversation
history bridging between host and container, tmux for session persistence,
GitHub CLI with auth forwarding, and starter Claude Code permissions.

## Files touched

- .devcontainer/Dockerfile
- .devcontainer/devcontainer.json
- .devcontainer/.inputrc
- .devcontainer/initializeCommand/capture-claude-env.sh
- .devcontainer/postCreateCommand/setup-claude-code.sh
- .claude/settings.json
- .claude/settings.json.repo-mixin.jsonc
- .claude/manage_settings.py
- .gitignore
- CLAUDE.md
- docs/devcontainer-setup.md

## Composability patterns

- **Post-create hooks**: `postCreateCommand` in devcontainer.json uses object format. Each mixin adds a named entry. Scripts live in `.devcontainer/postCreateCommand/`.
- **Initialize hooks**: `initializeCommand` in devcontainer.json uses object format. Scripts live in `.devcontainer/initializeCommand/`.
- **.gitignore**: marked sections with `# --- repo-mixin:<name> ---` delimiters. Add entries within your mixin's markers.
- **Dockerfile**: annotated blocks with `[repo-mixin:<name>]`. Add your mixin's blocks with annotations.
