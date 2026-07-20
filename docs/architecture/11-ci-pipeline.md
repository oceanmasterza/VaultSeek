# 11 — CI/CD Pipeline

## Policy

**Every commit must pass CI before merge.** CI runs from Phase 1 — the first line of application code is gated.

No AI-generated or human-written change ships without:
- `ruff check` (linting)
- `black --check` (formatting)
- `mypy --strict` (type checking)
- `pytest` (tests)

Tagged releases additionally build the PyInstaller executable.

---

## GitHub Actions Workflows

### `ci.yml` — Runs on Every Push and PR

```yaml
name: CI

on:
  push:
    branches: [master, main, develop]
  pull_request:
    branches: [master, main, develop]

jobs:
  lint:
    name: Lint & Format
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
          cache: pip

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Ruff lint
        run: ruff check src/ tests/

      - name: Black format check
        run: black --check src/ tests/

      - name: Import boundary check
        run: lint-imports

  typecheck:
    name: Type Check
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
          cache: pip

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Mypy strict
        run: mypy src/ --strict

  test:
    name: Test
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
          cache: pip

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Generate test audio fixtures
        run: python tests/fixtures/generate_audio.py

      - name: Run tests with coverage
        run: pytest --cov=vaultseek --cov-report=xml --cov-fail-under=80

      - name: Upload coverage
        if: github.event_name == 'push'
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
```

### `release.yml` — Runs on Version Tags

```yaml
name: Release

on:
  push:
    tags:
      - "v*.*.*"

jobs:
  build:
    name: Build Windows Executable
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
          cache: pip

      - name: Install dependencies
        run: pip install -e ".[dev,build]"

      - name: Run full test suite
        run: pytest

      - name: Build executable
        run: pyinstaller packaging/vaultseek.spec --noconfirm

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: VaultSeek-${{ github.ref_name }}-windows
          path: dist/VaultSeek/
```

---

## Tool Configuration (`pyproject.toml`)

```toml
[project]
name = "vaultseek"
requires-python = ">=3.14"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-qt>=4.4",
    "mypy>=1.10",
    "ruff>=0.5",
    "black>=24.0",
    "import-linter>=2.0",
    "responses>=0.25",
]
build = [
    "pyinstaller>=6.0",
]

[tool.ruff]
target-version = "py314"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "ANN", "B", "SIM"]

[tool.black]
line-length = 100
target-version = ["py314"]

[tool.mypy]
python_version = "3.14"
strict = true
packages = ["vaultseek"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "performance: performance benchmarks (excluded from CI by default)",
]

[tool.coverage.run]
source = ["src/vaultseek"]
fail_under = 80

[tool.importlinter]
root_packages = ["vaultseek"]

[[tool.importlinter.contracts]]
name = "Domain isolation"
type = "forbidden"
source_modules = ["vaultseek.domain"]
forbidden_modules = [
    "vaultseek.gui",
    "vaultseek.infrastructure",
    "vaultseek.application",
]

[[tool.importlinter.contracts]]
name = "GUI isolation"
type = "forbidden"
source_modules = ["vaultseek.gui"]
forbidden_modules = [
    "vaultseek.infrastructure",
]
```

---

## Branch Protection (Recommended)

Configure on GitHub repository settings:

| Rule | Setting |
|------|---------|
| Require status checks | `lint`, `typecheck`, `test` |
| Require branches up to date | Yes |
| Require pull request reviews | 1 reviewer (when contributors join) |
| Do not allow bypassing | Yes |

---

## Local Development Commands

```powershell
# Install dev dependencies
pip install -e ".[dev]"

# Run all checks (same as CI)
ruff check src/ tests/
black --check src/ tests/
mypy src/ --strict
pytest

# Auto-fix
ruff check --fix src/ tests/
black src/ tests/
```

### Pre-commit Hook (Optional, Phase 1)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: mypy src/ --strict
        language: system
        types: [python]
        pass_filenames: false
```

---

## CI Failure Policy

| Failure | Action |
|---------|--------|
| Ruff lint error | Fix before merge; no `# noqa` without justification |
| Black formatting | Run `black src/ tests/` and commit |
| Mypy error | Fix type annotation; no `# type: ignore` without comment |
| Test failure | Fix test or code; never skip tests to pass CI |
| Coverage below 80% | Add tests for new code |

---

## Why CI From Phase 1

Building CI after months of development means:
- Hundreds of untyped, untested lines accumulate
- First CI run fails with hundreds of errors
- "Fix CI" becomes a multi-day task

Starting CI on the scaffold (Phase 1) means:
- Every subsequent phase adds typed, tested, linted code
- Architectural boundaries enforced by import-linter from day one
- AI-generated code cannot introduce regressions silently
