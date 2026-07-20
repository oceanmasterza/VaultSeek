# VaultSeek

**Find what you're missing** — a Windows companion to [MusicVault](https://github.com/oceanmasterza/MusicVault) that discovers, scores, and acquires missing albums and tracks, then imports them through the same library pipeline.

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()

> **MusicVault** — Organise what you have.  
> **VaultSeek** — Find what you're missing.

## Status

**Phase 1 complete** — forked from MusicVault, rebranded, tests green. Acquisition Engine skeleton (`AcquisitionJob` + `ProviderManager` stub) in place. Nicotine+ provider and missing-media analysis are next.

Planning docs: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md), [docs/ARCHITECTURAL_UPDATE_001.md](docs/ARCHITECTURAL_UPDATE_001.md), [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md).

## Development

```powershell
cd C:\Users\user\Projects\VaultSeek
python -m pip install -e ".[dev]"
python -m pytest -q
```

Data directory (separate from MusicVault): `%APPDATA%\VaultSeek`

## License

MIT — see [LICENSE](LICENSE).
