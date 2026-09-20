# Music sources — what VaultSeek uses, and what else can fill gaps

This is for operators and third-party AI. Product behaviour lives in
[AGENTS.md](../AGENTS.md) and [PROWLARR.md](PROWLARR.md).

## Automated in VaultSeek today (waterfall)

| Order (default) | Source | Typical quality | Notes |
|-----------------|--------|-----------------|-------|
| 1 | Nicotine+ / Soulseek | FLAC to low-bitrate MP3, peer-dependent | Rate-limited; best for obscure / old rips |
| 2 | Usenet via Prowlarr → SABnzbd or NZBGet | Often scene lossless or 320 | One Usenet downloader; SABnzbd is the default |
| 3 | Prowlarr **public** torrents → qBittorrent | Mixed; seeders matter | Set a seeder floor in Plugins |
| 4 | Prowlarr **private** torrents → qBittorrent | Often the cleanest digital copies | Last by default; respect ratio/API caps |

Users can reorder this in Settings → Acquisition. Stop-after-first-hit is on by default.

## Identification (not downloaders)

| Service | Role | Signup |
|---------|--------|--------|
| Chromaprint / fpcalc | Local fingerprint | Bundled; else [Chromaprint](https://acoustid.org/chromaprint) |
| AcoustID | Match fingerprint → MusicBrainz | [New application](https://acoustid.org/new-application) — **application** key. Multiple keys/proxies in Settings |
| MusicBrainz | Canonical releases / tracklists | No key for normal lookup |
| Discogs | Editions, catalog, artwork | [Developers token](https://www.discogs.com/settings/developers) |
| Shazamio | Fallback recognizer | No account field; optional proxies |

## Recommendations (Wishlist only — never download)

- Last.fm similar artists — [API account](https://www.last.fm/api/account/create)
- Spotify playlist mirror — [Dashboard](https://developer.spotify.com/dashboard) (Client Credentials; 2026 Development Mode is limited)

## What we cannot auto-import

Detection reads **local config files** only. It cannot:

- Create paid accounts or accept terms
- Recover qBittorrent / Plex password hashes
- Add Prowlarr indexers or Usenet servers
- Install the Nicotine `api-nicotine-plus` plugin
- Enable a disabled qBittorrent Web UI

Those need the in-app **Setup instructions** (F1) plus the vendor UI.

## Additional sources (manual or future providers)

These are useful for missing music at different qualities. They are **not**
VaultSeek acquisition providers unless noted.

| Source | Quality | How to use with VaultSeek | Candidate for a later provider? |
|--------|---------|---------------------------|----------------------------------|
| Your CDs / NAS / old backups | Original | Rip lossless; copy into Incoming | Local/NAS folder search would help |
| Bandcamp purchases | FLAC / ALAC / MP3 | Artist store; import completed downloads | Possible with user login |
| Qobuz store (not stream cache) | CD / hi-res | Buy files, then Incoming | Store search links only |
| Internet Archive / Live Music Archive | Variable live/historical | Check item rights; extract then Incoming | Yes — permitted downloads only |
| Artist / label stores, Beatport, etc. | Licensed digital | Purchase → Incoming | Unlikely as a generic plugin |
| MusicBrainz Picard | Tagging, not acquisition | Identify files VaultSeek already has | Complementary tool |
| slskd | Soulseek via REST | Alternative to Nicotine+ | Possible second Soulseek client |
| ListenBrainz | Taste recommendations | Similar to Last.fm | Possible recommender |
| Lidarr / Headphones | Other *arr apps | Complementary library managers | Do not duplicate inside VaultSeek |
| Private trackers (RED, OPS, …) | Often high | Add in **Prowlarr**, not in VaultSeek | Already covered via `prowlarr_private` |

Do **not** add unofficial stream-rippers (Deemix, yt-dlp of commercial catalogs)
as first-party providers.

## Quality guidance

- Everyday listening: a good lossy original (MP3 320 / AAC) is enough.
- Archive: lossless originals (FLAC/ALAC). Transcoding MP3→FLAC is not an upgrade.
- Hi-res: require a real hi-res source and the intended mastering; bit depth in a
  filename is not proof.

Compare edition, track count, and audible quality before replacing a copy.

## Recommended development order (if adding providers)

1. Local/NAS archive search (user-owned files)
2. Permitted Internet Archive downloads
3. slskd as an optional Soulseek transport
4. Store “open in browser” links + import assistance for Bandcamp/Qobuz
