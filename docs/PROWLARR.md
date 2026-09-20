# Prowlarr + qBittorrent + SABnzbd

VaultSeek searches Prowlarr once per **tier**, then routes downloads:

| Provider id | What it searches | Download client |
|-------------|------------------|-----------------|
| `usenet` | Usenet / NZB results | **SABnzbd by default, or NZBGet** |
| `prowlarr_public` | Torrents from **public** indexers | **qBittorrent** |
| `prowlarr_private` | Torrents from **private** indexers | **qBittorrent** |

These ids are separate acquisition providers so the **search waterfall** can try Nicotine+, then Usenet, then public trackers, then private trackers (reorderable in Settings).

Enable **Prowlarr** plus the matching download client(s) under **System → Plugins**:

- Prowlarr + the selected Usenet client (SABnzbd by default, or NZBGet) → enables `usenet`
- Prowlarr + qBittorrent → enables `prowlarr_public` and `prowlarr_private`

## Ports (avoid clashes)

| App | Typical URL | Notes |
|-----|-------------|--------|
| Prowlarr | `http://127.0.0.1:9696` | API key: Settings → General |
| SABnzbd | `http://127.0.0.1:8080` | API key: Config → General |
| NZBGet | `http://127.0.0.1:6789` | Control username and password (not an add-only user) |
| qBittorrent | `http://127.0.0.1:8081` | VaultSeek default — **do not** share 8080 with SABnzbd |

If qBittorrent WebUI is still on 8080 while SABnzbd owns `127.0.0.1:8080`,
VaultSeek will talk to SABnzbd by mistake. Change qBittorrent:

1. Tools → Options → Web UI → Port **8081**
2. Restart qBittorrent
3. Set the same URL in VaultSeek Plugins

## Local setup detection

In **Plugins**, choose **Detect local download clients**. VaultSeek reads the
standard Windows configuration files for Prowlarr, qBittorrent, SABnzbd and NZBGet,
then shows each detected connection for review. Select the values you want to
copy, test them, enable the relevant providers, then save plugin settings.

Detection never edits third-party configuration, enables a provider, or changes
saved settings until you select an item and save. It preserves a configured
SABnzbd URL base such as `/sabnzbd`. It can read Prowlarr and SABnzbd API keys
but cannot recover qBittorrent's password because qBittorrent stores a hash.
Portable, Docker and remote installations need manual URLs and credentials.

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

1. In **Config → Servers**, add and test your Usenet provider. This account is
   separate from a Prowlarr indexer account.
2. In **Config → General**, copy the full **API Key** (not the NZB-only key).
3. Optional: category `vaultseek`.
4. In Plugins: enable SABnzbd, URL, API key, category.

The VaultSeek check verifies authenticated queue access. A server version page
can be public, so a successful browser page alone does not confirm the key works.

## NZBGet

NZBGet is an optional client for the same Usenet search tier. It is not a
second search source. SABnzbd remains the default.

1. In NZBGet Settings → News-servers, add and test the Usenet provider.
2. In Settings → Security, use the **control** username and password in
   VaultSeek. A restricted add-only login can append an NZB but cannot report
   queue or history, so the connection test fails it on purpose.
3. Optional: category `vaultseek`.
4. In Plugins, choose NZBGet as the Usenet downloader, enable NZBGet, test, and save.

New NZBs go only to the selected client. A download already sent to SABnzbd
keeps a `sab:` handle and is not submitted again to NZBGet. VaultSeek does not
edit `nzbget.conf` or the active queue during detection.
See [the NZBGet API](https://nzbget.com/documentation/api/).

## Search waterfall

Under **Settings → Wishlist & downloads**:

- Reorder Nicotine+ / Usenet / Prowlarr public / Prowlarr private
- Toggle “stop after first source that finds results”
- Set delay (seconds) after an empty source before trying the next

Defaults favour Soulseek first, then Usenet, then public torrents, then private.

## Legacy note

Older configs used a single `prowlarr` (or `prowlarr_qbit`) provider id. Schema **v22** expands that into `usenet` + `prowlarr_public` + `prowlarr_private`. A combined `prowlarr` provider may still exist in-process for compatibility; prefer the split ids.
