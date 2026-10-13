# Carry-On

Searchable archive of your ChatGPT / Claude / Gemini history, served to AI assistants over MCP.

## 1. Configure
Set **secret** to a random string of at least 32 characters, e.g. the output of
`python -c "import secrets;print(secrets.token_urlsafe(32))"`, then start the add-on.
Your endpoint is `https://<host>/<secret>/mcp`. The whole URL works like a password.

## 2. Import your history
Copy export zips unchanged into `/share/carryon/inbox/` (the `share` folder of the Samba
add-on). Every 5 minutes the add-on imports new files and moves them to
`/share/carryon/imported/`; the log shows the counts. Re-export and drop new zips whenever
you like: conversations are deduplicated by id and last update.

| Source | How to export |
|---|---|
| ChatGPT | Settings → Data controls → Export data |
| Claude | Settings → Privacy → Export data |
| Gemini | takeout.google.com → My Activity (JSON format) → only "Gemini Apps" |

## 3. Expose it (built-in Tailscale Funnel)
Free, no domain or router changes needed.
1. Enable **tailscale_funnel** (device name = **tailscale_hostname**, default `carryon`), restart.
2. Open the `https://login.tailscale.com/...` link printed in the log and approve the device.
3. If the log says `Funnel is not enabled on your tailnet`, open the link it gives.
4. The log prints `public endpoint: https://carryon.<tailnet>.ts.net/<secret>/mcp`.
   Public DNS for a new name can take a few minutes.

Tailscale runs in userspace inside the container and only forwards to port 8765; its state is
kept in the add-on's `/data`. Its output is discarded because it can contain request paths.
Do **not** forward the port on your router.

## 4. Connect your assistant
- **Claude**: Settings → Connectors → Add custom connector → paste the URL.
- **ChatGPT**: Settings → Apps & Connectors → Advanced → enable Developer mode, then create a
  connector with the URL and authentication "No auth".
- Any other MCP client: streamable HTTP at the same URL.

## Notes
- Search is keyword-based (SQLite FTS5 trigram). Terms shorter than 3 characters fall back
  to a slower substring scan.
- Gemini Takeout deletes activity older than 18 months; older messages already in the
  archive are kept and merged on re-import.
- Attachments are indexed by name (and extracted text where the export includes it), not stored.
