# Prowlarr + qBittorrent + SABnzbd

VaultSeek searches Prowlarr once per **tier**, then routes downloads:

| Provider id | What it searches | Download client |
|-------------|------------------|-----------------|
| `usenet` | Usenet / NZB results | **SABnzbd** |
| `prowlarr_public` | Torrents from **public** indexers | **qBittorrent** |
| `prowlarr_private` | Torrents from **private** indexers | **qBittorrent** |

These ids are separate acquisition providers so the **search waterfall** can try Nicotine+, then Usenet, then public trackers, then private trackers (reorderable in Settings).

Enable **Prowlarr** plus the matching download client(s) under **System → Plugins**:

- Prowlarr + SABnzbd → enables `usenet`
- Prowlarr + qBittorrent → enables `prowlarr_public` and `prowlarr_private`

## Ports (avoid clashes)

| App | Typical URL | Notes |
|-----|-------------|--------|
| Prowlarr | `http://127.0.0.1:9696` | API key: Settings → General |
| SABnzbd | `http://127.0.0.1:8080` | API key: Config → General |
| qBittorrent | `http://127.0.0.1:8081` | VaultSeek default — **do not** share 8080 with SABnzbd |

If qBittorrent WebUI is still on 8080 while SABnzbd owns `127.0.0.1:8080`,
VaultSeek will talk to SABnzbd by mistake. Change qBittorrent:

1. Tools → Options → Web UI → Port **8081**
2. Restart qBittorrent
3. Set the same URL in VaultSeek Plugins

## Prowlarr

1. Add audio indexers (Torznab / Newznab as you prefer). Tag Cloudflare-blocked public indexers for FlareSolverr if you use it.
2. Copy the API key.
3. In VaultSeek Plugins: enable Prowlarr, paste URL + key, set minimum seeders
   for torrents (NZBs ignore seeders).
4. **Test Prowlarr**.

Category **3000** (Audio) is the default search filter.

Privacy for public vs private tiers comes from each indexer’s Prowlarr `privacy` field (refreshed on connect).

## qBittorrent

1. Enable Web UI; note username / password.
2. Optional: create category `vaultseek` (VaultSeek can set it on add).
3. Point completed downloads somewhere VaultSeek can read (or leave the
   default and rely on category paths).
4. In Plugins: enable qBittorrent, URL, credentials, category.

## SABnzbd

1. Enable API; copy API key.
2. Optional: category `vaultseek`.
3. In Plugins: enable SABnzbd, URL, API key, category.

## Search waterfall

Under **Settings → Wishlist & downloads**:

- Reorder Nicotine+ / Usenet / Prowlarr public / Prowlarr private
- Toggle “stop after first source that finds results”
- Set delay (seconds) after an empty source before trying the next

Defaults favour Soulseek first, then Usenet, then public torrents, then private.

## Legacy note

Older configs used a single `prowlarr` (or `prowlarr_qbit`) provider id. Schema **v22** expands that into `usenet` + `prowlarr_public` + `prowlarr_private`. A combined `prowlarr` provider may still exist in-process for compatibility; prefer the split ids.
