# VaultSeek

**Find what you're missing** — a Windows desktop app that completes and improves your music library through searchable download sources, verification, and the same organize / artwork / media-server pipeline you already use day to day.

[![CI](https://github.com/oceanmasterza/VaultSeek/actions/workflows/ci.yml/badge.svg)](https://github.com/oceanmasterza/VaultSeek/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()
[![Version](https://img.shields.io/badge/version-1.1.0-informational.svg)](CHANGELOG.md)

VaultSeek is an **Acquisition Engine**: it analyses your library, finds missing or improvable releases, searches external sources through pluggable **providers**, scores hits, downloads, **verifies** every file, imports into Incoming, and refreshes media servers.

Data lives under `%APPDATA%\VaultSeek`.

---

## Features

### Library & processing

- Watch Incoming, scan, hash, fingerprint, identify
- Metadata: MusicBrainz, AcoustID, Shazamio fallback, Discogs, local tags, filename parser
- Review queue, rules, organize into Library, artwork (embedded + Cover Art Archive)
- Browse UI: Library, Artists, Albums, Artwork, Duplicates
- Media servers: Navidrome, Jellyfin, Plex, Emby, Subsonic, Ampache, Koel, Funkwhale, Lyrion
- Dashboard, Jobs, Activity, Reports, Setup wizard

### Acquisition

- **Wishlist** — park albums, auto-search / download when ready
- **Nicotine+** — Soulseek search & download (HTTP api-nicotine-plus or NDJSON socket)
- **Usenet** — Prowlarr NZB search → **SABnzbd**
- **Prowlarr torrents** — public then private indexers → **qBittorrent**
- **Search waterfall** — try sources in order; stop when a tier finds hits (reorderable in Settings)
- Missing-media & quality-upgrade scans
- Scoring, verification, import pipeline

### Discovery (opt-in Plugins page)

- **Similar music (Last.fm)** — albums by artists similar to your library
- **Spotify playlist sync** — mirror public playlists into the Wishlist

Everything on the Plugins page is **off by default** so the core stays lean.

---

## Architecture (short)

```mermaid
flowchart LR
  Library[Library gaps] --> Engine[Acquisition Engine]
  Engine --> Search[Search Dispatcher]
  Search --> Waterfall[Waterfall order]
  Waterfall --> Nic[Nicotine+]
  Waterfall --> Usenet[Usenet via Prowlarr]
  Waterfall --> Pub[Prowlarr public]
  Waterfall --> Priv[Prowlarr private]
  Nic --> Score[Scoring]
  Usenet --> Score
  Pub --> Score
  Priv --> Score
  Score --> DL[Download Manager]
  DL --> Verify[Verify and import]
  Verify --> Library
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

---

## Quick start

```powershell
git clone https://github.com/oceanmasterza/VaultSeek.git
cd VaultSeek
python -m pip install -e ".[dev]"
python -m vaultseek
```

Or download a Windows build from [Releases](https://github.com/oceanmasterza/VaultSeek/releases).

**First run:** create a library (Incoming / Staging / Library / Archive), then enable providers under **System → Plugins** and **Settings**.

---

## Documentation

| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md) | **AI assistants** — repo map, waterfall, settings ownership, GitLab `main` |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) / in-app **F1** | Setup, where to change settings, download options |
| [docs/PROWLARR.md](docs/PROWLARR.md) | Prowlarr tiers + qBittorrent + SABnzbd |
| [docs/NICOTINE_PLUS.md](docs/NICOTINE_PLUS.md) | Nicotine+ HTTP / socket |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers and pipelines |
| [docs/AI_RULES.md](docs/AI_RULES.md) | Coding / docs rules for humans and AI |
| [CHANGELOG.md](CHANGELOG.md) | Released versions |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup |

---

## Development

| | |
|---|---|
| **Version** | 1.1.0 |
| **Stack** | Python 3.12+, PySide6, SQLite / SQLAlchemy 2, Alembic |
| **Tests** | `python -m pytest -q` |
| **Lint** | ruff, black, mypy (strict), import-linter |

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

---

## License

MIT — see [LICENSE](LICENSE).
