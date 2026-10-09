# Google Calendar plugin (local MCP)

Codex plugin for Google Calendar backed by a **local stdio MCP server**
(`bin/gcal_mcp.py`) that talks to the **public Google Calendar API v3** using
**your own Google Cloud OAuth client**.

## Why a local server instead of `calendarmcp.googleapis.com`?

Upstream (`openai/plugins`) points this plugin at
`https://calendarmcp.googleapis.com/mcp/v1` with an OpenAI-provided OAuth
client. That server currently requires the Google Cloud project to be enrolled
in the **Google Workspace Developer Preview Program**
(<https://developers.google.com/workspace/preview>, manual allowlist with
~2-day review). Without enrollment, every tool call fails with
`... is enrolled in the Google Workspace Developer Preview Program`.

The MCP server is only a wrapper over the **public** Calendar REST API
(`https://www.googleapis.com/calendar/v3`), which has **no preview gate**.
This fork replaces the remote MCP with a local one so the plugin works with
zero dependency on OpenAI connectors or Google preview programs.

## Tools

Same names as Google's official MCP server:

| Tool | Description |
| --- | --- |
| `list_calendars` | List calendars of the signed-in account |
| `list_events` | List events (optional time range / free-text filter) |
| `get_event` | Fetch one event by id |
| `search_events` | Search events by free-text query |
| `create_event` | Create an event (datetimes or all-day, attendees, location) |
| `update_event` | Update fields of an existing event |
| `delete_event` | Delete an event |
| `respond_to_event` | RSVP to an invitation (accepted / declined / tentative) |

## Setup (one time)

1. In [Google Cloud Console](https://console.cloud.google.com/), create an
   **OAuth client of type "Desktop app"** (any project works; no billing) and
   enable the **Calendar API** for it. Configure the OAuth consent screen and
   add your Google account as a **test user** (Testing mode is enough — no
   app review needed).
2. Save the client credentials (never commit them; they stay outside this
   repo):

   ```json
   // ~/.codex/gcp_oauth_client.json
   {
     "client_id": "....apps.googleusercontent.com",
     "client_secret": "GOCSPX-..."
   }
   ```

3. Run the one-time auth (opens the Google consent page in your browser):

   ```sh
   python3 bin/gcal_auth.py
   ```

   Tokens are stored in `$CODEX_HOME/gcal_token.json` (default
   `~/.codex/gcal_token.json`, permissions `600`) together with the client
   credentials needed to refresh them. The MCP server auto-refreshes expired
   access tokens.
4. Install the plugin and reload Codex:

   ```sh
   codex plugin add google-calendar@gabo-curated
   ```

In **Codex Desktop**, MCP tools require approval on first use: keep
`approval_policy = "on-request"` in `~/.codex/config.toml` (with `never`,
new MCP tools are silently rejected and the model reports "no connector
connected"). Approve the first `google-calendar` tool call (choose "always
allow" to avoid repeated prompts).

## Verify

Ask in a Codex session: *"list my calendars"*. A working install returns the
calendars of the signed-in account. In the CLI you can also probe the server
directly:

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 bin/gcal_mcp.py
```

## Security notes

- This repository is public: **no secrets live here**. The OAuth client JSON
  and the token file stay in `~/.codex/` (outside git).
- The server only requests Calendar scopes and only calls Google APIs.

## Troubleshooting

- **`invalid_grant` on refresh** — the refresh token was revoked or expired:
  in "Testing" consent mode Google expires refresh tokens after ~7 days.
  Either publish the app (needs verification for broad use) or simply re-run
  `python3 bin/gcal_auth.py`.
- **Tools blocked / "no connector connected"** — approval policy `never`
  rejects new MCP tools silently; switch to `on-request` (see Setup step 4).
- **Marketplace update overwrites local edits** — changes to this plugin must
  be committed to the fork (`d3athbian/plugins`, marketplace `gabo-curated`);
  `marketplace upgrade` re-syncs the cache from git.

## Keeping in sync with upstream (`openai/plugins`)

This plugin is **self-contained**: `bin/` + `.mcp.json` + `.codex-plugin/` +
`assets/`. Upstream releases only touch UI/metadata, so staying current with
Google tooling is a light sync:

1. Fetch upstream: `git remote add upstream https://github.com/openai/plugins.git`
   (or `git fetch upstream` if it exists) and diff
   `upstream:plugins/google-calendar` against this directory:

   ```sh
   git fetch upstream
   git diff HEAD upstream/main -- plugins/google-calendar/
   ```
2. **Take from upstream** (safe to copy): `assets/` (icons/logos), and
   cosmetic metadata in `.codex-plugin/plugin.json` (`interface` block,
   descriptions).
3. **Never take from upstream** (local-owned, this fork's whole point):
   - `.mcp.json` — must stay `stdio` + `python3 ./bin/gcal_mcp.py` (upstream
     points to the preview-gated `calendarmcp.googleapis.com`).
   - `.codex-plugin/plugin.json` → no `apps` key (upstream re-adds it).
   - `.app.json` — do not restore (upstream ships it).
   - `bin/` — upstream does not have these files; keep them.
4. Bump the minor/patch version, reinstall
   (`codex plugin add google-calendar@gabo-curated`), and verify with
   *"list my calendars"*.

## Differences from upstream `openai/plugins` v1.2.6

- `.mcp.json`: remote HTTP MCP with placeholder OAuth client → local stdio
  server (`python3 ./bin/gcal_mcp.py`).
- `.app.json` (connector app reference) removed, along with the `apps` key in
  `.codex-plugin/plugin.json` — the official connector is not provisioned for
  non-premium accounts (install returns 404 / zero tools).
- Version bumped to `1.3.0`.
