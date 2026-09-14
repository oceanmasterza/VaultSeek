# VaultSeek user guide

The same guide is in the app: **Help → VaultSeek Help** or **F1**.
This page is the GitHub copy.

VaultSeek organizes a personal music library and can search download sources
for missing tracks or better-quality copies. It does not replace Nicotine+,
Prowlarr, qBittorrent, or SABnzbd — those programs do the searching and
downloading. VaultSeek talks to them, then treats finished files like anything
you dropped in Incoming.

---

## Install and data folder

- **Installer / portable build:** [GitHub Releases](https://github.com/oceanmasterza/VaultSeek/releases)
- **From source:** `python -m pip install -e ".[dev]"` then `python -m vaultseek`
- **Config and database:** `%APPDATA%\VaultSeek\` (`config.json`, `vaultseek.db`, logs)

Only one VaultSeek window may run at a time (SQLite lock).

---

## First library

1. On first launch the **Setup wizard** opens (or use **Help → Setup wizard…**).
2. Set **Incoming** and **Library**. Staging and Archive are optional; blank
   fields become sibling folders.
3. Optionally connect Nicotine+, paste Discogs / AcoustID keys, pick a quality preset.
4. **Save**, then **Scan Incoming** (File menu, Dashboard, or Settings).

Files stay in Incoming through identify / review, then move to Library when
approved.

---

## Where to change settings

Use the page that owns the field, then click **that page’s** Save button.

| What you want to change | Open | Save button |
|-------------------------|------|-------------|
| Incoming / Library folders, watch, identify auto-approve | Settings → Library | **Save library** |
| Quality preset, lossless / bitrate, whole-album upgrades | Settings → Library quality | **Save preferences** |
| Wishlist interval, auto-acquire score, Nicotine+, search source order | Settings → Wishlist & downloads | **Save preferences** |
| Theme, log level, Discogs, AcoustID, fingerprinting | Settings → Application | **Save preferences** |
| Navidrome / Jellyfin / Plex / other servers | Settings → Media servers | **Save media server** |
| Last.fm, Spotify, Prowlarr, qBittorrent, SABnzbd | System → Plugins | **Save plugin settings** |

**Detect local installs:** Settings and Plugins each have a detect button. VaultSeek
reads standard Windows config for Prowlarr, qBittorrent, SABnzbd, Nicotine+,
Jellyfin, Navidrome, Plex and Emby. It copies URLs/keys you select; it does not
enable providers or recover hashed passwords. Test, then Save.

Full API signup steps: in-app Help (F1) → Connection setup. Extra source ideas:
[SOURCES.md](SOURCES.md).

Settings has three Save buttons. Plugins has its own. Editing Nicotine+ and
clicking **Save library** does not write those Nicotine+ fields.

Theme and log level apply immediately. Discogs, AcoustID, Shazamio, and
fingerprint mode need a **restart**. Prowlarr / download clients reconnect
when you save Plugins.

The Dashboard **shows** the wishlist search interval. Change it only in
Settings (use **Change in Settings** on the Dashboard).

---

## How the app is laid out

| Hub | Pages | Use it for |
|-----|-------|------------|
| Home | Dashboard | Health, pipeline, getting started |
| Library | Files, Artists, Albums, Artwork, Duplicates | What you already have |
| Find & get | Find music, Review, Wishlist | Gaps, Discogs, approvals, downloads |
| System | Jobs, Activity, Reports, Logs, Settings, Plugins | Background work and configuration |

**Ctrl+K** opens Jump to…. The toolbar **Library** combo switches collections.

### Folders (zones)

| Folder | Required | Purpose |
|--------|----------|---------|
| Incoming | Yes | Drop zone. Downloads land here after verify. Stays here until approved. |
| Library | Yes | Organized collection. |
| Staging | No | Optional hold folder. Suggested as a sibling if blank. |
| Archive | No | Duplicates and rejects. Suggested as a sibling if blank. |

**Identify auto-approve** (Settings → Library, default 0.90) is the
identification confidence that skips Review. **Download auto-acquire**
(Settings → Wishlist & downloads, default 0.45) is the search-match score
that starts a download without you picking a result. They are different.

### Day to day

1. Put audio in Incoming (or let a download finish there).
2. **File → Scan Incoming** (or Watch Incoming). Watch **Jobs**.
3. Clear **Review** if needed.
4. Browse Library / Artists / Albums. Green = meets quality prefs; orange = missing or below prefs.
5. **Find music** → Find missing songs or Discogs → then **Wishlist** → Auto-acquire.
6. Parked Discogs picks are **Wanted**. On Wishlist, enable **Show Wanted**, then **Start Wanted download**.

---

## Which download setup?

Enable only what you actually run.

| Your setup | Enable in VaultSeek |
|------------|---------------------|
| Soulseek only | Settings → Wishlist & downloads → Enable Nicotine+ |
| Torrents only | Plugins → Prowlarr + qBittorrent |
| Usenet only | Plugins → Prowlarr + SABnzbd |
| Torrents and Usenet | Plugins → Prowlarr + qBittorrent + SABnzbd |
| Soulseek plus indexers | Nicotine+ in Settings, and Prowlarr plus at least one download client on Plugins |
| Suggestions only | Plugins → Last.fm and/or Spotify (they never download files) |

Prowlarr by itself cannot download. Enable Prowlarr **and** qBittorrent
(torrents) and/or SABnzbd (NZBs). Hits that need a client you left off are skipped.

### How a download works

1. You queue a job (Find missing, Discogs, or a manual album).
2. Connected sources search.
3. Hits are scored against title, artist, format, and quality prefs.
4. If the score meets Download auto-acquire, download starts; otherwise pick a result on Wishlist.
5. Files are verified, copied into Incoming, then scanned and organized as usual.

Missing-track jobs try a **whole album** first, then fall back to per-track
search. Background wishlist passes use the interval in Settings (0 = as often
as rate limits allow).

### Search source order (waterfall)

Settings → Wishlist & downloads. Default order: Nicotine+ → Usenet →
Prowlarr public → Prowlarr private.

- **Stop after the first source that finds results** (default on): later
  sources are skipped once a connected source returns hits.
- **Wait after an empty source** (default 15 seconds): pause before the next
  tier when the current one found nothing.
- A Nicotine+ rate-limit error does not block later tiers.
- Turn waterfall off to search every connected source every time.
- Plugins still enable Prowlarr / qBittorrent / SABnzbd. Reorder does not
  turn sources on.

---

## Soulseek (Nicotine+)

VaultSeek talks to [Nicotine+](https://nicotine-plus.org/) on the same PC.
Prefer **HTTP (api-nicotine-plus)** on port **12339**.

1. Install Nicotine+, log into Soulseek, keep it running.
2. Install the **api-nicotine-plus** plugin.
3. Settings → Wishlist & downloads → enable Nicotine+, transport HTTP, port `12339`, optional token.
4. **Test Nicotine+ connection**, then **Save preferences**.

Search rate limits default to 5 seconds between searches and 8 per minute
to avoid Soulseek flood bans. Advanced NDJSON socket transport is documented
in [NICOTINE_PLUS.md](NICOTINE_PLUS.md).

---

## Prowlarr, qBittorrent, SABnzbd

Configure on **System → Plugins**. Details: [PROWLARR.md](PROWLARR.md).

| App | Typical URL | Credential |
|-----|-------------|------------|
| Prowlarr | `http://127.0.0.1:9696` | Settings → General → API Key |
| SABnzbd | `http://127.0.0.1:8080` | Config → General → API Key |
| qBittorrent | `http://127.0.0.1:8081` | Web UI user / password |

If SABnzbd uses 8080, put qBittorrent on **8081** (VaultSeek’s default) so
the two do not collide.

1. Add audio indexers in Prowlarr. Enable Prowlarr in Plugins; **Test Prowlarr**.
2. Enable qBittorrent and/or SABnzbd; use the matching Test button.
3. **Save plugin settings**.
4. Queue one album on Find music, then Wishlist → Auto-acquire.

Torrents go to qBittorrent; NZBs go to SABnzbd.

---

## Last.fm and Spotify

On **Plugins**. Suggestions land on Wishlist as parked items. They never
download by themselves.

1. Enable Last.fm and/or Spotify, enter credentials.
2. For Spotify, paste **public** playlist URLs (one per line). Web API access
   typically needs Spotify Premium on the developer-app account.
3. Save, then **Find recommendations now**.

Already-owned and already-listed albums are skipped.

---

## Quality presets

Settings → Library quality. These drive orange/green colors and upgrade scans.

| Preset | Meaning |
|--------|---------|
| Completist | Prefer lossless. No lossy bitrate floor. |
| Collector | Prefer lossless. Lossy at least 320 kbps. (Wizard default.) |
| Lossy OK | Prefer MP3, min 192 kbps. |
| Custom | You edited the fields by hand. |

---

## Discogs and AcoustID

Optional tokens in **Settings → Application**. Restart after saving.

- Discogs: [developers settings](https://www.discogs.com/settings/developers) — genre/label/catalog and Discogs browse.
- AcoustID: [new application](https://acoustid.org/new-application) — **application** key (not a user submission key). **Add another account / connection** adds more keys or proxy routes (also used by Shazamio fallback).

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| F1 | This help |
| Ctrl+Shift+S | Scan Incoming |
| Ctrl+D / L / F / R / W / J | Dashboard / Library / Find music / Review / Wishlist / Jobs |
| Ctrl+, | Settings |
| Ctrl+K | Jump to… |
| F5 | Refresh |
| Ctrl+Enter / Ctrl+Shift+R | Approve / reject on Review |

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Searches return nothing | Test buttons in Settings (Nicotine+) or Plugins (Prowlarr). Nicotine+ logged in? |
| Waterfall never reaches Prowlarr | First source already had hits. Reorder or turn waterfall off in Settings → Wishlist & downloads. |
| Prowlarr finds hits, no download | qBittorrent and/or SABnzbd enabled? Ports? Save Plugins. |
| qBittorrent login failed | Port clash with SABnzbd? Try `http://127.0.0.1:8081` |
| SABnzbd probe fails | API key under SABnzbd → Config → General |
| Waiting for user | Score below Download auto-acquire — Pick result… or lower the threshold |
| Discogs asks for a token | Settings → Application, Save preferences, restart |
| Second window exits | Another VaultSeek is already running |

Logs: `%APPDATA%\VaultSeek\logs\` (`vaultseek.log`, `debug.log`).
**File → Open Log Folder** or **System → Logs**.

In the app:

- **Help → Setup wizard** — folders, Nicotine+, optional tokens
- **Help → About** — version and data paths
- **System → Plugins** — recommenders and Prowlarr / download clients
- **System → Settings** — library, quality, Nicotine+, Discogs/AcoustID, media servers
