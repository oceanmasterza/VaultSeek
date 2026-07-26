# Changelog

All notable changes to VaultSeek are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Full-repo CI green (black / ruff / mypy / import-linter debt cleanup)
- Albums page N+1 query rewrite (fold track metadata into browse query)

## [1.1.0] - 2026-07-26

### Added

- **SABnzbd download client** — opt-in Usenet downloads via SABnzbd when Prowlarr
  returns NZB results (config schema v21)
- **Prowlarr multi-client provider** — one `prowlarr` acquisition backend routes
  torrents to qBittorrent and NZBs to SABnzbd based on which clients are enabled
- **User guide** (`docs/USER_GUIDE.md`) and Prowlarr setup notes (`docs/PROWLARR.md`)
- Dashboard acquisition stats use SQL `COUNT` / `GROUP BY` instead of loading every job

### Changed

- Public README reframed as a standalone product (no MusicVault companion marketing)
- Version bumped to 1.1.0 across package, installer, and setup scripts
- Plugins page documents SABnzbd alongside Prowlarr / qBittorrent

### Fixed

- Headless bootstrap-failure test no longer depends on a free single-instance lock
- Removed dead `StubPage` / unused plugin marker / empty `viewmodels` package
- Ignore agent/build diagnostic `_*.txt` and `packaging/_*` leftovers
- qBittorrent WebUI login accepts HTTP 204 / localhost auth bypass (qBittorrent 5.x)
- Default qBittorrent URL uses port **8081** so it does not clash with SABnzbd on 8080
- Prowlarr search errors are logged and return no hits instead of raising

### Known debt

- Repo-wide black / mypy / import-linter still need a dedicated cleanup PR

## [1.0.0] - 2026-07-24

### Added

- Stable restore point: UI hang fixes (async tasks + debounced inputs), Nicotine+ HTTP
  transport, acquisition state-machine transition fixes
- Opt-in recommenders: Last.fm similar music, Spotify playlist sync → Wishlist
- Prowlarr + qBittorrent torrent acquisition provider
- Plugins management UI

### Notes

- Earlier Unreleased phase history through Phase 16 remains in git history; this
  file now tracks released versions going forward.
