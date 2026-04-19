#!/bin/bash
# [repo-mixin:devcontainer-claude] Claude Code notification hook.
# Extracts the session's most recent user prompt from the transcript and
# POSTs a structured payload to the local notification listener so it can
# render a messaging-app-style notification: project / session / status.
# Invoked from settings.json for PermissionRequest and Stop events.
set -euo pipefail

payload=$(cat)
transcript=$(printf '%s' "$payload" | jq -r '.transcript_path // ""')
title=""
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
  # Prefer Claude's auto-generated session title (the one shown in /resume).
  # Take the most recent ai-title in case the session was re-titled.
  title=$(jq -r 'select(.type=="ai-title") | .aiTitle // empty' "$transcript" 2>/dev/null | tail -n 1)
  # Fall back to the most recent user prompt, stored on line 1 as a last-prompt entry.
  if [ -z "$title" ]; then
    title=$(head -n 1 "$transcript" | jq -r '.lastPrompt // empty' 2>/dev/null || true)
  fi
fi

printf '%s' "$payload" | jq -c --arg title "$title" '{
  event: .hook_event_name,
  tool: .tool_name,
  detail: (.tool_input.command // .tool_input.file_path // .tool_input.pattern // .tool_input.url // ""),
  cwd: .cwd,
  title: $title
}' | curl -s -d @- "http://${CLAUDE_NOTIFY_HOST:-localhost}:61009" >/dev/null || true
