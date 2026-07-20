# Contributing to VaultSeek

Thank you for considering a contribution. VaultSeek favors explicit structure, strict typing, and small reviewable changes.

## Before You Start

Read the planning and architecture docs — they are the source of truth:

1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design and Acquisition Engine model
2. [docs/ARCHITECTURAL_UPDATE_001.md](docs/ARCHITECTURAL_UPDATE_001.md) — required reading before new features
3. [docs/ROADMAP.md](docs/ROADMAP.md) — public phase status (what is open for work)
4. [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) — internal engineering notebook
5. [docs/AI_RULES.md](docs/AI_RULES.md) — conventions for humans and AI assistants

Heritage MusicVault pipeline docs live under [docs/architecture/](docs/architecture/) (import pipeline, DB schema, testing).

**Before implementing a feature:** confirm the phase is marked ready in ROADMAP. Propose architectural changes in [docs/DECISIONS.md](docs/DECISIONS.md) or a GitHub discussion first.

## GitHub Project Board

Work is tracked on the [VaultSeek project board](https://github.com/users/oceanmasterza/projects/1) (owner: `oceanmasterza`).

Columns (**Stage** field): **Ideas** → **Architecture Ready** → **Ready for Development** → **In Progress** → **Testing** → **Completed**

If the board view shows default Status columns instead of Stage, open the project → board view → **Group by** → **Stage**.

If you cannot access the board, open an issue describing your proposal and reference the relevant doc section.

### Board setup (maintainers)

The project was created via `scripts/setup-github-project.ps1`. To recreate or repair the board (requires `gh` `project` scope):

```powershell
gh auth refresh -h github.com -s project,read:project
.\scripts\setup-github-project.ps1
```

## Development Setup

Requires Python 3.14+ (stdlib `uuid.uuid7()` for primary keys).

```powershell
git clone https://github.com/oceanmasterza/VaultSeek.git
cd VaultSeek
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Running Checks Locally

Run the same checks CI runs before opening a pull request:

```powershell
ruff check src/ tests/
black --check src/ tests/
mypy src/ --strict
pytest
```

Auto-fix what can be auto-fixed:

```powershell
ruff check --fix src/ tests/
black src/ tests/
```

Verify architectural layer boundaries:

```powershell
lint-imports
```

## Code Standards

- **Type annotate everything.** `mypy --strict` must pass.
- **Use dataclasses** for entities and DTOs.
- **No global mutable state.** Use `vaultseek.core.container.Container`.
- **Respect layer boundaries** — see [docs/architecture/02-folder-layout.md](docs/architecture/02-folder-layout.md).
- **Terminology:** Acquisition Engine, AcquisitionJob, Provider, Verification Pipeline, Import Pipeline.
- **Documentation-first:** update ARCHITECTURE / ROADMAP / ADRs when design changes.
- **Write tests** with new code in the same pull request.

## Commit and PR Conventions

- Imperative summary line; body explains *why*.
- Prefixes encouraged: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`.
- One logical change per PR.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes.
- Update architecture docs when design decisions change.

## Testing Strategy

See [docs/architecture/09-testing-strategy.md](docs/architecture/09-testing-strategy.md).

- `tests/unit/` — pure logic, mocked dependencies
- `tests/integration/` — filesystem / DB via `tmp_path`
- No live external APIs in CI

## Reporting Issues

Include VaultSeek version, Windows version, and relevant lines from `%APPDATA%\VaultSeek\logs\`. Redact personal paths if needed.

## License

Contributions are licensed under the [MIT License](LICENSE).
