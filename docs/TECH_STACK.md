# TECH_STACK.md

Technical overview of VaultSeek — what is actually in the repository today.

---

## Application stack

| Component | Technology | Notes |
|-----------|------------|-------|
| **Language** | Python 3.12+ | UUIDv7 PKs (stdlib on 3.14+, polyfill on 3.12/3.13); 3.12 preferred for Shazamio Windows wheels |
| **Package** | `vaultseek` | `src/vaultseek/` layout, setuptools |
| **Desktop UI** | PySide6 (Qt 6) | Windows-first; pages under `vaultseek/gui/` |
| **Persistence** | SQLite | Single file under `%APPDATA%\VaultSeek\` |
| **ORM / migrations** | SQLAlchemy 2, Alembic | Schema in `vaultseek/db/` |
| **Dependency injection** | `vaultseek.core.container.Container` | Explicit bootstrap wiring, no globals |
| **Job queue** | Custom dispatcher + worker tiers | Scan/hash (CPU), I/O workers for metadata/artwork |
| **Logging** | loguru | Structured logs under `%APPDATA%\VaultSeek\logs\` |
| **Config** | Versioned JSON | `vaultseek.core.config`, schema migrations |
| **Plugin contracts** | `typing.Protocol` | Metadata, artwork, acquisition, media-server |

### UI and presentation

- Qt widgets + thin page controllers (`gui/views/`)
- Business logic lives in `services/` and `workers/`, not in GUI modules
- import-linter enforces GUI → no direct DB/worker imports

### Acquisition (VaultSeek-specific)

| Piece | Status | Location |
|-------|--------|----------|
| `AcquisitionJob` + state machine | Implemented | `models/entities/acquisition_job.py` |
| `AcquisitionEngine` | Skeleton (in-memory) | `services/acquisition_engine.py` |
| `AcquisitionProvider` protocol | Implemented | `models/interfaces/acquisition.py` |
| `ProviderManager` | Implemented | `services/provider_manager.py` |
| Stub provider | Placeholder | `plugins/builtin/acquisition_stub/` |

---

## External services

### Metadata (implemented)

| Service | Purpose | Auth |
|---------|---------|------|
| **MusicBrainz** | Recording / release lookup | User-Agent required; 1 req/s |
| **AcoustID** | Fingerprint → MBID | Application key in Settings |
| **Discogs** | Genre, label, catalog, covers | Personal access token |
| Local embedded tags | Mutagen read | None |
| Filename parser | Regex extraction | None |

### Artwork (implemented)

| Source | Priority |
|--------|----------|
| Cover Art Archive | 10 |
| Discogs | 20 |
| Embedded (Mutagen) | 50 |

### Media servers (implemented — rescan trigger)

Navidrome, Jellyfin, Emby, Plex, Subsonic, Ampache, Koel, Funkwhale, Lyrion.

### Acquisition providers (planned)

| Provider | Status |
|----------|--------|
| **Nicotine+** | Planned (first real provider) |
| Local archive, SMB, FTP, WebDAV, Lidarr, … | Future |

VaultSeek does **not** embed the Soulseek protocol. Nicotine+ is an external client accessed through a Provider plugin.

---

## Development environment

### Required tools

- Windows 10/11 (primary target)
- Python 3.12+
- Git
- [GitHub CLI](https://cli.github.com/) (`gh`) — optional, for issues/projects

### Build and test

```powershell
git clone https://github.com/oceanmasterza/VaultSeek.git
cd VaultSeek
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

```powershell
# Same checks as CI
ruff check src/ tests/
black --check src/ tests/
mypy src/ --strict
lint-imports
pytest
```

### Windows installer

```powershell
.\packaging\build_windows.ps1
```

Output: `packaging/output/VaultSeek-Setup.exe` (local build artifact).

### Data directories

| App | Path |
|-----|------|
| VaultSeek | `%APPDATA%\VaultSeek` |
| MusicVault (companion) | `%APPDATA%\MusicVault` |

Libraries are compatible; app data is kept separate.

### Workflow

1. Read [ARCHITECTURAL_UPDATE_001.md](ARCHITECTURAL_UPDATE_001.md) before architectural changes
2. Update [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) session notes after significant work
3. Add ADR entries to [DECISIONS.md](DECISIONS.md) for new architectural decisions
4. Small, reviewable PRs; tests with behavior changes

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [AI_RULES.md](AI_RULES.md).
