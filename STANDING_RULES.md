# VaultSeek Standing Rules

## Scope and terminology

- Build a Windows desktop Acquisition Engine in Python 3.12+ and PySide6.
- Use **Acquisition Engine**, **AcquisitionJob**, **Provider**, **Verification Pipeline**, and **Import Pipeline**. Do not call it a Search Engine.
- Treat `AGENTS.md`, `docs/AI_RULES.md`, and `docs/DECISIONS.md` as the detailed, authoritative rules. This file is their compact working index.

## Architecture and configuration

- UI calls application services from `Container`; it never calls a Provider, repository, or worker directly.
- Providers only communicate with external systems. They never mutate the library, UI, database, or media server.
- Reuse a typed service, Protocol, repository, or widget before adding another one.
- Keep config in typed dataclasses. A schema change requires a migration and matching `config/defaults.json` update.
- Preserve nested acquisition settings with `dataclasses.replace`; never rebuild `AcquisitionConfig` or a nested config object on a page save.
- Respect settings ownership: Settings owns library, quality, wishlist, Nicotine+, application, and media-server values; Plugins owns Last.fm, Spotify, Prowlarr, qBittorrent, SABnzbd, NZBGet, and the Usenet client choice (`usenet_download_client`, SABnzbd default).

## Code and quality

- Python has strict mypy typing; do not introduce untyped escapes or broad `Any` outside an unavoidable boundary.
- Prefer small, named functions, composition, dependency injection, explicit error handling, and structured `loguru` logging.
- Avoid globals, hidden static state, duplicate helpers, magic strings, deep conditionals, and unrelated refactors.
- Use `pathlib`, immutable dataclass replacement, and cancellation/progress support for long-running work where applicable.
- Keep public behavior safe: preview or archive before destructive library changes; never commit secrets.

## Tests and documentation

- Add focused unit tests for business logic. Mock external services; never fake live indexer or Soulseek behavior.
- Run the relevant tests plus ruff, black, mypy, and import-linter for changed code before review.
- Update architecture/ADR/roadmap/help documentation in the same change when behavior, ownership, or architecture changes.
- Before completing a significant task, update `PROJECT_CONTEXT.md` or this file only when their concise shared facts changed; record decisions in `CHANGELOG_DECISIONS.md`.

## Working method

- For a task affecting three or more files or core logic, state a five-item-or-fewer plan and wait for approval or adjustments before implementation, unless the active task already explicitly authorizes implementation.
- Read only directly affected files and their architecture contracts. Work in small testable chunks.
- Communicate with paths, symbols, tests, and concise diffs; do not paste whole files unless asked.
