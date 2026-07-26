# VaultSeek user guide

This guide covers first-run setup and the optional download / discovery plugins.
In-app tooltips and the Setup wizard cover the same ground with less detail.

## Install & data folder

- **Installer / portable build:** [GitHub Releases](https://github.com/oceanmasterza/VaultSeek/releases)
- **From source:** `python -m pip install -e ".[dev]"` then `python -m vaultseek`
- **Config & database:** `%APPDATA%\VaultSeek\` (`config.json`, `vaultseek.db`, logs)

Only one VaultSeek instance may run at a time (SQLite lock).

## First library

1. Open **Settings** (or the Setup wizard on first launch).
2. Set four folders: **Incoming**, **Staging**, **Library**, **Archive**.
3. Save, then **Scan Incoming** (or File → Scan Incoming).

Files stay in Incoming through identify / review, then move to Library when approved.

## Acquisition overview

Wishlist items are parked `AcquisitionJob`s. Promote them (or enable auto-queue)
so the engine can **search → score → download → verify → import**.

| Source | Where to enable | Role |
|--------|-----------------|------|
| Nicotine+ | Settings → Acquisition | Soulseek search & download |
| Prowlarr | Plugins | Indexer search |
| qBittorrent | Plugins | Torrent downloads from Prowlarr |
| SABnzbd | Plugins | Usenet / NZB downloads from Prowlarr |
| Last.fm / Spotify | Plugins | Suggest albums into Wishlist only |

## Nicotine+

See [NICOTINE_PLUS.md](NICOTINE_PLUS.md). Prefer **HTTP (api-nicotine-plus)** on port
12339. Use **Test Nicotine+ connection** in Settings before relying on auto-acquire.

## Prowlarr, qBittorrent, SABnzbd

See [PROWLARR.md](PROWLARR.md). Important on this machine layout:

- If **SABnzbd** uses `http://127.0.0.1:8080`, put **qBittorrent WebUI on 8081**
  (or another free port). VaultSeek defaults qBittorrent to port **8081**.

## Discovery recommenders

On **Plugins**:

1. Enable Last.fm and/or Spotify, enter API credentials.
2. For Spotify, paste public playlist URLs (one per line).
3. Save, then **Find recommendations now**.

Suggestions are de-duplicated against owned albums and existing Wishlist entries.
They never download by themselves — promote Wishlist items when you want them.

## Discogs & AcoustID

Optional tokens in **Settings → Application**. Discogs improves genre / label /
covers; AcoustID (and optional proxies) powers fingerprint lookup. Restart after
saving metadata keys.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Searches return nothing | Provider connected? Nicotine+ / Prowlarr Test buttons |
| qBittorrent “login failed” | Port clash with SABnzbd? Try `http://127.0.0.1:8081` |
| SABnzbd probe fails | API key under SABnzbd → Config → General |
| App hangs on typing | Update to 1.0.0+ (debounced search / background tasks) |
| Illegal job transition | Update to 1.0.0+ acquisition state-machine fixes |
| Second window exits quietly | Another VaultSeek is already running |

Logs: `%APPDATA%\VaultSeek\logs\` (`vaultseek.log`, `debug.log`). Help → Open log folder.

## Help in the app

- **Help → Setup wizard** — folders, Nicotine+, optional tokens
- **Help → About** — version and data paths
- **System → Plugins** — recommenders and Prowlarr / download clients
- **System → Settings** — library, quality presets, Nicotine+, media servers
