# devcontainer-python-uv mixin

Applied from: https://github.com/mrjogo/repo-mixin/tree/main/mixins/devcontainer-python-uv
Applied commit: 56d6d32dfacb61a3c58306653e64234023e52b6c
Applied: 2026-05-09

## What this does

Sets up a devcontainer for Python projects managed with uv. Pins Python 3.12, installs uv via Astral's upstream installer, and runs `uv sync --frozen` on container create so the virtualenv is ready on first terminal open.

## Files touched

- .devcontainer/Dockerfile
- .devcontainer/devcontainer.json

## Composability patterns

- **Dockerfile**: annotated blocks with `[repo-mixin:devcontainer-python-uv]`. This mixin owns the `FROM` and `USER` directives by convention.
- **Post-create hooks**: `postCreateCommand` in devcontainer.json uses object format. Adds a `uv-sync` entry alongside other mixins' entries.
