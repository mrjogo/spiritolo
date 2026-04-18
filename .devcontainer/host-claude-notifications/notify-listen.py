#!/usr/bin/env python3
# [repo-mixin:devcontainer-claude] Lightweight HTTP listener on localhost:61009 that shows
# native macOS notifications when Claude Code needs attention.
# Install to ~/.claude/notify-listen.py on your Mac.
# Requires: brew install terminal-notifier

import http.server
import json
import os
import shutil
import subprocess
import sys

PORT = 61009
ICON = os.path.expanduser("~/.claude/claude-icon.png")
NOTIFIER = (
    shutil.which("terminal-notifier")
    or "/opt/homebrew/bin/terminal-notifier"
)

if not os.path.isfile(NOTIFIER):
    print("terminal-notifier not found. Install with: brew install terminal-notifier", file=sys.stderr)
    sys.exit(1)


def osascript_raise_window(project):
    """Build an osascript shell command that activates VS Code and raises the matching window.
    Deep-linking into the extension's sidebar session isn't supported —
    vscode://anthropic.claude-code/open?session=<id> opens a new editor tab instead of
    switching the sidebar. Tracked in anthropics/claude-code#40169. Until that ships, we
    just raise the window and let the user use the sidebar's own session picker."""
    safe = project.replace('"', '\\"')
    return (
        'osascript'
        ' -e \'tell application "Visual Studio Code" to activate\''
        ' -e \'tell application "System Events" to tell process "Code"'
        f' to perform action "AXRaise" of (first window whose title contains "{safe}")\''
    )


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else "{}"
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            data = {"event": "Notification", "detail": raw}

        event = data.get("event", "Notification")
        cwd = data.get("cwd", "")
        project = os.path.basename(cwd) if cwd else "Claude Code"
        title = (data.get("title") or "").strip()
        if len(title) > 80:
            title = title[:77].rstrip() + "…"

        if event == "PermissionRequest":
            message = "Needs permission"
        elif event == "Stop":
            message = "Finished"
        else:
            detail = data.get("detail", str(raw))
            message = detail if detail else "Needs attention"

        cmd = [
            NOTIFIER,
            "-title", project,
            "-message", message,
            "-sound", "Submarine",
            "-execute", osascript_raise_window(project),
        ]
        if title:
            cmd += ["-subtitle", title]
        if os.path.isfile(ICON):
            cmd += ["-contentImage", ICON]
        subprocess.Popen(cmd)

    def log_message(self, *args):
        pass


http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
