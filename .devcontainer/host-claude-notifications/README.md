<!-- [repo-mixin:devcontainer-claude] Host-side macOS notification setup for Claude Code.
     These files are installed to the developer's Mac by Claude Code at mixin apply time.
     __HOME__ placeholders in companion files are replaced with the user's home directory. -->

# host-claude-notifications

Native macOS notifications when Claude Code needs your attention. Works uniformly across local, devcontainer, and remote SSH environments by running a tiny HTTP listener on `localhost:61009`.

```
Claude Code hook → stdin JSON → jq → curl localhost:61009 → listener on Mac → macOS notification
```

Notifications are formatted like a messaging app: **project** (top), **session title** (middle), status (bottom). Clicking a notification raises the matching VS Code window. No external services — everything runs locally on your Mac.

## Install (One-Time, on Your Mac)

**1. Install terminal-notifier:**

```bash
brew install terminal-notifier
```

**2. Copy the listener script:**

```bash
cp notify-listen.py ~/.claude/notify-listen.py
```

**3. (Optional) Add a Claude icon:**

Save a Claude logo PNG to `~/.claude/claude-icon.png` and it will appear on notifications. Any square PNG works — grab the logo from your Anthropic account or the Claude app.

```bash
# If you have the Claude macOS app installed, borrow its icon:
sips -s format png /Applications/Claude.app/Contents/Resources/electron.icns --out ~/.claude/claude-icon.png 2>/dev/null
```

**4. Install the launchd agent:**

```bash
cp local.claude-notify-listener.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/local.claude-notify-listener.plist
```

**5. Test:**

```bash
# Rich JSON (what hooks actually send):
curl -s -d '{"event":"PermissionRequest","tool":"Bash","detail":"npm install","cwd":"/my/project","title":"Refactor the auth flow"}' http://localhost:61009

# Plain text still works too:
curl -s -d "test notification" http://localhost:61009
```

## Payload format

POST a JSON body to `http://localhost:61009`. Plain text bodies are also accepted as a fallback and displayed as-is.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event` | string | no | Hook event name. Recognized values: `PermissionRequest`, `Stop`. Defaults to `Notification`. |
| `tool` | string | no | Tool that triggered the notification (e.g. `Bash`, `Edit`, `Write`). Reserved for future use. |
| `detail` | string | no | Context string — typically the command, file path, or URL. Used as the message for unknown event types. |
| `cwd` | string | no | Working directory. The basename is extracted and shown as the notification title. |
| `title` | string | no | Session title — Claude's auto-generated `ai-title` (the one in the `/resume` picker), or the most recent user prompt as a fallback. Shown as the subtitle. Truncated to 80 chars. |

All fields are optional. A POST with an empty or non-JSON body produces a generic "Claude Code" notification.

## What you'll see

| Event | Title | Subtitle | Message |
|-------|-------|----------|---------|
| Permission | *myproject* | *Refactor the auth flow* | Needs permission |
| Finished | *myproject* | *Refactor the auth flow* | Finished |

Clicking any notification brings VS Code to the front. The Claude logo appears on the right if `~/.claude/claude-icon.png` exists.

## VS Code Insiders

If you use VS Code Insiders, change the `-activate` bundle ID in `notify-listen.py`:

```python
'-activate', 'com.microsoft.VSCodeInsiders',
```

## Remote SSH

Add a reverse port forward so the remote host can reach your laptop's listener:

```
Host myremote
    RemoteForward 61009 localhost:61009
```

VSCode Remote SSH picks this up automatically. The hook works on the remote without changes.

## Devcontainers

Already handled — `CLAUDE_NOTIFY_HOST` is set to `host.docker.internal` in `devcontainer.json`, so the hook reaches the host's listener directly. No bridge process needed.

## Reloading after changes

```bash
launchctl unload ~/Library/LaunchAgents/local.claude-notify-listener.plist
launchctl load ~/Library/LaunchAgents/local.claude-notify-listener.plist
```
