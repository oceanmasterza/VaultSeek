# AGENTS.md — notes for third-party AI assistants

This file is the **onboarding brief** for any AI (Cursor, Claude Code, Codex, Copilot, Aider, etc.) working on VaultSeek. Read it before changing code.

Humans: see [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/AI_RULES.md](docs/AI_RULES.md).

---

## What VaultSeek is

Windows desktop **Acquisition Engine** (Python 3.12+, PySide6). It finds missing / upgradeable music, searches pluggable providers, scores hits, downloads, verifies, imports into Incoming, then organizes like a MusicVault-style library pipeline.

- Data dir: `%APPDATA%\VaultSeek`
- Package root: `src/vaultseek/`
- App entry: `python -m vaultseek` (from a venv with `pip install -e ".[dev]"`)

**Do not** invent a “Search Engine” architecture name. Use: Acquisition Engine, AcquisitionJob, Provider, Verification Pipeline, Import Pipeline.

---

## Mandatory reading (in order)

1. [docs/ARCHITECTURAL_UPDATE_001.md](docs/ARCHITECTURAL_UPDATE_001.md) — Acquisition Engine model
2. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers
3. [docs/DECISIONS.md](docs/DECISIONS.md) — ADRs (do not silently reverse)
4. [docs/AI_RULES.md](docs/AI_RULES.md) — coding / docs rules
5. [docs/architecture/02-folder-layout.md](docs/architecture/02-folder-layout.md) — import boundaries
6. Feature-specific: [docs/PROWLARR.md](docs/PROWLARR.md), [docs/NICOTINE_PLUS.md](docs/NICOTINE_PLUS.md), [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
7. Latest **Session Notes** in [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md)

If a change alters architecture: update ADRs + architecture docs **before** or with the code (see AI_RULES documentation-first section).

---

## Repository map (where to edit)

| Area | Path |
|------|------|
| DI / wiring | `src/vaultseek/core/container.py` |
| Typed config + migrations | `src/vaultseek/core/config.py` (`CURRENT_SCHEMA_VERSION`) |
| Default config JSON | `config/defaults.json` (must stay in sync with `AppConfig`) |
| Acquisition orchestration | `src/vaultseek/services/provider_manager.py`, `acquisition_*.py` |
| Search source order helpers | `src/vaultseek/services/acquisition_sources.py` |
| Nicotine+ provider | `src/vaultseek/plugins/builtin/nicotine_plus/` |
| Prowlarr tiers (Usenet / public / private) | `src/vaultseek/plugins/builtin/prowlarr_qbit/` |
| SABnzbd client | `src/vaultseek/plugins/builtin/sabnzbd/` |
| Settings UI | `src/vaultseek/gui/views/settings_page.py` |
| Plugins UI (Prowlarr / qBit / SAB / Last.fm / Spotify) | `src/vaultseek/gui/views/plugins_page.py` |
| Unit tests | `tests/unit/` |

UI must not call providers directly. Go through `ProviderManager` / services from `Container`.

---

## Acquisition search waterfall (current product behaviour)

Default **provider_order** (schema **v22+**):

1. `nicotine_plus` — Soulseek via Nicotine+
2. `usenet` — Prowlarr NZB / Usenet → SABnzbd
3. `prowlarr_public` — Prowlarr **public** torrents → qBittorrent
4. `prowlarr_private` — Prowlarr **private** torrents → qBittorrent

Behaviour (`ProviderManager.search`):

- `search_waterfall=True` (default): **stop after the first connected source that returns hits**
- `provider_search_delay_seconds` (default `15`): wait after an **empty** tier before trying the next
- Nicotine `SearchThrottleError` must **not** block later tiers
- Users reorder sources + delay under **Settings → Wishlist & downloads → Search source order**
- Enable Prowlarr / SABnzbd / qBittorrent under **Plugins**; Nicotine+ under Settings

Legacy id `prowlarr` / `prowlarr_qbit` expands to the three Prowlarr tiers on migrate/connect. Prefer the split ids in new code.

Key modules: `acquisition_sources.py`, `acquisition_bootstrap.py`, `provider_manager.py`, `ProwlarrProvider` (protocol + privacy filters), config migration `_migrate_v21_to_v22`.

---

## Config rules

- Never bump `CURRENT_SCHEMA_VERSION` without a `_migrate_vN_to_vN+1` and updating `config/defaults.json`
- Nested acquisition settings (`prowlarr`, `qbittorrent`, `sabnzbd`, `nicotine_plus`) live on `AcquisitionConfig`
- **One writer per nested field:** Settings saves Nicotine+ / waterfall / quality with `dataclasses.replace` on the existing `AcquisitionConfig`. Plugins saves Prowlarr / qBit / SAB the same way. Never rebuild `AcquisitionConfig(...)` from scratch — that wiped credentials.
- Strongly typed dataclasses only; no ad-hoc nested dict config for new features

---

## Settings vs Plugins ownership (do not duplicate writers)

| Setting | Owner page | Save button |
|---------|------------|-------------|
| Folders, watch, identify auto-approve | Settings → Library | **Save library** |
| Quality preset / lossless / bitrate / whole-album | Settings → Library quality | **Save preferences** |
| Wishlist interval, auto-acquire, Nicotine+, **search waterfall** | Settings → Wishlist & downloads | **Save preferences** |
| Theme, log level, Discogs, AcoustID, fingerprinting | Settings → Application | **Save preferences** |
| Media servers | Settings → Media servers | **Save media server** |
| Last.fm, Spotify, Prowlarr, qBittorrent, SABnzbd | System → Plugins | **Save plugin settings** |

- Dashboard shows wishlist hours as **read-only** (“Change in Settings”).
- Wanted management lives on **Wishlist**, not Albums.
- Log/report path pickers belong on **System → Logs**, not Settings → Library.
- Shared widgets: `gui/widgets/quality_fields.py`, `page_header.py`, `health_legend.py`.
- Setup wizard must update the **active** library (not `list_all()[0]`), use `replace()` for Nicotine+, write `acoustid_endpoints`, and must not reset onboarding tips on re-run.

---

## Multi-AI + GitLab coordination

Canonical remote: `gitlab` → `git@10.11.11.123:xpe-dev-main/vaultseek.git`. Primary branch: **`main`**.

Before you start a session:

1. `git fetch gitlab` and `git pull --ff-only gitlab main` (or rebase onto it). Do not assume `master` or GitHub `origin` is current.
2. Read this file, [docs/DECISIONS.md](docs/DECISIONS.md), and the latest **Session Notes** in [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md).
3. Leave notes the next AI can use: update Session Notes + ADRs when behaviour or ownership changes.

When you finish user-visible or architectural work:

1. Update `AGENTS.md` / ADRs / Session Notes in the **same commit** as the code.
2. Push **`gitlab main`** (`git push gitlab main`). Do **not** force-push. Do **not** retarget `origin`. Do **not** change git `user.*`.
3. `master` may lag `main`; do not merge them unless a human asks.

Do not overwrite another AI’s nested config fields. Settings vs Plugins ownership above is the merge contract.

---

## Commands (Windows)

```powershell
cd C:\OtherDev\VaultSeek   # also used: C:\Dev\VaultSeek
.\.venv\Scripts\activate
pip install -e ".[dev]"
ruff check src/ tests/
black --check src/ tests/
mypy src/ --strict
pytest -q
lint-imports
python -m vaultseek
```

Prefer the project `.venv` if present. CI expects the same checks.

---

## Git remote (this deployment)

Canonical remote for this machine’s VaultSeek work:

```text
git@10.11.11.123:xpe-dev-main/vaultseek.git
```

- Primary branch: **`main`**
- Auth: dedicated SSH key `~/.ssh/id_ed25519_xpedite_vaultseek` (deploy key). Do **not** use personal/admin API tokens for routine pushes.
- Do **not** retarget `origin` to other hosts/repos unless a human explicitly asks.
- Do **not** modify unrelated GitLab projects or global git `user.*` config.

---

## Hard constraints for AI sessions

- **Reuse** before inventing new services / providers
- **Providers** talk to external systems only — no library mutate, no UI, no media-server refresh
- **No secrets** in commits (API keys, tokens, private keys)
- **No** drive-by refactors unrelated to the task
- **No** large packaging/`packaging/output` or `_setup_staging` blobs in git (gitignored)
- Mark stubs clearly; do not fake live indexer/Soulseek behaviour in unit tests
- Prefer small, tested increments; update docs when behaviour changes

---

## Quick “where is X?”

| Need | Look here |
|------|-----------|
| Add acquisition source | New provider id + register in `container._build_acquisition_providers`, bootstrap enable rules, Settings order list labels in `acquisition_sources.py` |
| Change search stop/delay | `ProviderManager` + `AcquisitionConfig.search_waterfall` / `provider_search_delay_seconds` |
| Prowlarr privacy/protocol filter | `prowlarr_client.py` + `ProwlarrProvider(protocol_filter=..., privacy_filter=...)` |
| Schema migration test pattern | `tests/unit/core/test_config.py`, `test_recommendation_config.py` |
| Waterfall unit tests | `tests/unit/services/test_provider_manager.py` |

---

## Done checklist (AI)

Before finishing a task:

1. Relevant unit tests pass (`pytest` on touched areas; full `tests/unit` when risky)
2. No new mypy/ruff issues in edited files
3. `config/defaults.json` matches schema if config changed
4. Docs/ADR updated if architecture or user-visible acquisition behaviour changed
5. No secrets staged
