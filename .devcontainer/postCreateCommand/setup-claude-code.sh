#!/bin/bash
# [repo-mixin:devcontainer-claude] Bridge Claude Code project history and plugin paths between host and container.
# Claude Code stores conversation history keyed by absolute project path. Since the host path
# (e.g., /Users/you/projects/myapp) differs from the container path (e.g., /workspaces/myapp),
# this script creates symlinks so Claude finds the right history inside the container.
# Also bridges plugin paths that reference the host home directory.
#
# Requires: HOST_HOME env var and HOST_PROJECT_DIR from .env.devcontainer.
set -e

# Path mangling — Claude Code converts /foo/bar to -foo-bar for directory names
mangle() { echo "$1" | tr '/' '-'; }

CLAUDE_DIR="$HOME/.claude"

# Symlink host project history to container project path.
# Without this, Claude Code would create a new empty history for the container path
# instead of finding the existing history from host-side sessions.
if [ -n "$HOST_PROJECT_DIR" ]; then
    CONTAINER_PROJECT_DIR="$(pwd)"
    HOST_MANGLED=$(mangle "$HOST_PROJECT_DIR")
    CONTAINER_MANGLED=$(mangle "$CONTAINER_PROJECT_DIR")

    LINK="$CLAUDE_DIR/projects/$CONTAINER_MANGLED"
    TARGET="$CLAUDE_DIR/projects/$HOST_MANGLED"

    if [ "$HOST_MANGLED" != "$CONTAINER_MANGLED" ]; then
        if [ ! -d "$TARGET" ]; then
            mkdir -p "$TARGET"
            echo "Created project history directory: $TARGET"
        fi

        if [ -d "$LINK" ] && [ ! -L "$LINK" ]; then
            cp -an "$LINK"/. "$TARGET"/ 2>/dev/null || true
            rm -rf "$LINK"
            echo "Merged existing container history into $TARGET"
        fi

        ln -sfn -- "$HOST_MANGLED" "$LINK"
        echo "Linked project history: $LINK -> $TARGET"
    else
        echo "Skipped project history link (paths already match)"
    fi
fi

# Symlink host home .claude so plugin paths that reference
# the host home directory (e.g., /Users/you/.claude/plugins/...) resolve inside the container.
if [ -n "$HOST_HOME" ] && [ "$HOST_HOME" != "$HOME" ]; then
    sudo mkdir -p "$HOST_HOME"
    sudo ln -sfn "$CLAUDE_DIR" "$HOST_HOME/.claude"
    echo "Linked host home: $HOST_HOME/.claude -> $CLAUDE_DIR"
else
    echo "Skipped host home link (HOST_HOME not set or matches HOME)"
fi
