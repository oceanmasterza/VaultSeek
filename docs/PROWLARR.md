# Prowlarr + qBittorrent + SABnzbd

VaultSeek uses **one acquisition provider** (`prowlarr`) that:

1. Searches indexers through **Prowlarr**
2. Sends **torrent** hits to **qBittorrent**
3. Sends **Usenet / NZB** hits to **SABnzbd**

Enable Prowlarr plus **at least one** download client under **System → Plugins**.

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

1. Add audio indexers (Torznab / Newznab as you prefer).
2. Copy the API key.
3. In VaultSeek Plugins: enable Prowlarr, paste URL + key, set minimum seeders
   for torrents (NZBs ignore seeders).
4. **Test Prowlarr**.

Category **3000** (Audio) is the default search filter.

## qBittorrent

1. Enable Web UI; note username / password.
2. Optional: create category `vaultseek` (VaultSeek can set it on add).
3. Point completed downloads somewhere VaultSeek can read (or leave the
   default save path — completed paths are reported via the WebUI API).
4. **Test qBittorrent** in Plugins.

## SABnzbd

1. Configure your Usenet server in SABnzbd (outside VaultSeek).
2. Copy the API key.
3. Enable SABnzbd in Plugins; paste URL + key; optional category `vaultseek`.
4. **Test SABnzbd**.

Completed jobs should land under SABnzbd’s complete folder; VaultSeek reads
audio files from the history `storage` path after status is Completed.

## Routing rules

| Prowlarr protocol / link | Client used |
|--------------------------|-------------|
| `torrent`, magnet, `.torrent` | qBittorrent (if enabled) |
| `usenet`, `.nzb` | SABnzbd (if enabled) |
| Hit needs a client that is off | Skipped in search results |

## Verify end-to-end

1. Save Plugins settings; restart VaultSeek if prompted.
2. Wishlist → add an album → promote / Auto-acquire.
3. Confirm the job moves Searching → Downloading → Verifying → Completed.
4. Check Incoming for imported files.

Do not point VaultSeek at production indexers for bulk copyrighted downloads
you do not have rights to; use the stack for libraries you are authorized to
complete.
