# Contributing to VaultSeek

Thank you for considering a contribution. VaultSeek is built to eventually
support hundreds of contributors, so the project favors explicit structure,
strict typing, and small reviewable changes over speed.

## Before You Start

Read the architecture documentation first — it is the source of truth for
how the codebase is organized and *why*:

1. [docs/architecture/12-pipeline-engine-v3.md](docs/architecture/12-pipeline-engine-v3.md) — current execution model
2. [docs/architecture/02-folder-layout.md](docs/architecture/02-folder-layout.md) — where code lives
3. [docs/architecture/07-roadmap.md](docs/architecture/07-roadmap.md) — what phase we're in and what's next

Only the phase currently in progress (see the roadmap) is open for
implementation work. Architectural changes are far cheaper before code
exists than after — if you want to propose a design change, open a
discussion referencing the relevant architecture document before writing
code.

## Development Setup

Requires Python 3.14+ (needed for the standard library's native `uuid.uuid7()`,
used to generate every primary key in the schema — see
[Database Schema](docs/architecture/03-database-schema.md)).

```powershell
git clone https://github.com/vaultseek/vaultseek.git
cd vaultseek
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Running Checks Locally

Run the same checks CI runs, in this order, before opening a pull request:

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

Verify architectural layer boundaries are respected:

```powershell
lint-imports
```

## Code Standards

- **Type annotate everything.** `mypy --strict` must pass with zero errors
  and zero `# type: ignore` comments unless accompanied by a comment
  explaining why the ignore is unavoidable.
- **Use dataclasses** for entities, value objects, and DTOs. Prefer
  `@dataclass(frozen=True)` unless mutability is required and justified.
- **No global mutable state.** Dependencies are threaded through
  explicitly via `vaultseek.core.container.Container`, not module-level
  singletons.
- **Respect layer boundaries** (see
  [docs/architecture/02-folder-layout.md](docs/architecture/02-folder-layout.md)).
  `models/` never imports from `db/`, `services/`, `workers/`, or `gui/`.
  Workers never write to SQLite directly — they emit `WriteDTO`s to the
  database writer queue (from Phase 4 onward).
- **No toy code.** Every function should behave correctly for the
  documented edge cases, not just the happy path demonstrated in a test.
- **Write tests as you go.** New code ships with unit tests (and
  integration tests where I/O is involved) in the same pull request.
- **No narrating comments.** Comments explain *why*, not *what* — the code
  itself should make the "what" obvious.

## Commit and PR Conventions

- Commit messages: short imperative summary line, blank line, body
  explaining *why* the change was made. Conventional prefixes
  (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`) are encouraged.
- One logical change per pull request. Large refactors should be
  discussed against the architecture docs first.
- Update `CHANGELOG.md` under `[Unreleased]` for any user-visible or
  architecturally significant change.
- Update the relevant `docs/architecture/*.md` file if your change alters
  a documented design decision.

## Testing Strategy

See [docs/architecture/09-testing-strategy.md](docs/architecture/09-testing-strategy.md)
for the full test pyramid, fixture conventions, and naming scheme
(`test_{what}_{condition}_{expected}`). In short:

- `tests/unit/` — pure logic, no I/O, mocked dependencies
- `tests/integration/` — real filesystem/database interactions via
  temporary directories (`tmp_path` fixture)
- Never hit real external APIs in tests — use recorded fixtures or the
  `responses` library

## Reporting Issues

Include your VaultSeek version, Windows version, and (if relevant) the
contents of `%APPDATA%/VaultSeek/logs/debug.log` around the time of the
issue. Redact any personal file paths you're not comfortable sharing.

## License

By contributing, you agree that your contributions will be licensed under
the project's [MIT License](LICENSE).
