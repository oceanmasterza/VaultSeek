# 09 — Testing Strategy

## Test Pyramid

```
         ╱  E2E  ╲          Manual GUI testing (Phase 12+)
        ╱──────────╲
       ╱ Integration ╲       Service + infrastructure tests
      ╱────────────────╲
     ╱    Unit Tests     ╲    Domain services, value objects, utilities
    ╱──────────────────────╲
```

| Level | Count Target | Run Time | When |
|-------|-------------|----------|------|
| Unit | 200+ | < 10 seconds | Every commit (CI) |
| Integration | 50+ | < 2 minutes | Every commit (CI) |
| E2E / GUI | 10+ | < 5 minutes | Pre-release manual |

## Test Infrastructure

### Directory Structure

```
tests/
├── conftest.py                 # Shared fixtures
├── unit/
│   ├── domain/
│   │   ├── test_quality_scorer.py
│   │   ├── test_duplicate_matcher.py
│   │   ├── test_rename_engine.py
│   │   └── test_organize_engine.py
│   ├── application/
│   │   ├── test_scanner_service.py
│   │   ├── test_metadata_service.py
│   │   └── test_duplicate_service.py
│   └── core/
│       ├── test_config.py
│       └── test_config_migration.py
├── integration/
│   ├── test_database.py
│   ├── test_scanner.py
│   ├── test_fingerprint.py
│   ├── test_metadata.py
│   ├── test_duplicates.py
│   ├── test_organizer.py
│   ├── test_rollback.py
│   └── test_plugins.py
└── fixtures/
    ├── audio/                  # Generated test audio files
    ├── metadata/               # Recorded API responses (JSON)
    └── config/                 # Sample configuration files
```

### Core Fixtures (`conftest.py`)

```python
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from vaultseek.core.container import Container

@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Isolated app data directory for each test."""
    data_dir = tmp_path / "VaultSeek"
    data_dir.mkdir()
    (data_dir / "logs").mkdir()
    (data_dir / "cache").mkdir()
    return data_dir

@pytest.fixture
def test_db(tmp_data_dir: Path) -> str:
    """In-memory SQLite database with full schema."""
    db_path = tmp_data_dir / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    # Run migrations
    yield str(db_path)
    engine.dispose()

@pytest.fixture
def container(test_db: str, tmp_data_dir: Path) -> Container:
    """Fully wired DI container with test database."""
    return Container.create_for_testing(
        db_path=test_db,
        data_dir=tmp_data_dir,
    )

@pytest.fixture
def sample_tracks(container: Container) -> list[int]:
    """Insert 10 sample tracks into test database, return IDs."""
    ...

@pytest.fixture
def audio_fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "audio"
```

### Test Audio Fixtures

Generated programmatically in CI (not stored in repo):

```python
# tests/fixtures/generate_audio.py (run in CI setup)
def generate_test_files(output_dir: Path) -> None:
    """Create minimal valid audio files for testing."""
    # 3-second silent FLAC (16-bit, 44100 Hz)
    # 3-second silent MP3 (320 kbps)
    # 3-second silent M4A (AAC)
    # 1 corrupt file (truncated header)
    # 1 file with embedded artwork
    # 1 file with MusicBrainz tags
```

Uses FFmpeg to generate minimal valid files (~50 KB each).

### Recorded API Responses

MusicBrainz/AcoustID responses recorded once, replayed in tests:

```
tests/fixtures/metadata/
├── acoustid_lookup_success.json
├── acoustid_lookup_no_match.json
├── musicbrainz_recording.json
├── musicbrainz_release.json
├── musicbrainz_search_results.json
└── cover_art_archive_front.json
```

Tests never hit real APIs — all HTTP mocked via `responses` library.

## Unit Tests

### Domain Layer (100% coverage target)

```python
# tests/unit/domain/test_quality_scorer.py

class TestQualityScorer:
    def test_flac_24bit_scores_100(self):
        track = make_track(codec="flac", bit_depth=24)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 100

    def test_flac_16bit_scores_95(self):
        track = make_track(codec="flac", bit_depth=16)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 95

    def test_mp3_320_scores_70(self):
        track = make_track(codec="mp3", bitrate=320)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 70

    def test_ranks_lossless_above_lossy(self):
        flac = make_track(codec="flac", bit_depth=16)
        mp3 = make_track(codec="mp3", bitrate=320)
        ranked = QualityScorer(DEFAULT_WEIGHTS).rank([mp3, flac])
        assert ranked[0] is flac

    def test_custom_weights(self):
        weights = QualityWeights(mp3_320=90)
        track = make_track(codec="mp3", bitrate=320)
        assert QualityScorer(weights).score(track) == 90
```

```python
# tests/unit/domain/test_rename_engine.py

class TestRenameEngine:
    @pytest.mark.parametrize("input,expected", [
        ("Allen_Watts_-_Indicator-(KR147)-SINGLE-16BIT-WEB-FLAC-2024-FMC", "Allen Watts - Indicator"),
        ("Artist_-_Album-[AFO]-WEB-FLAC", "Artist - Album"),
        ("01_-_Track_Name", "01 - Track Name"),
    ])
    def test_cleans_scene_names(self, input, expected):
        assert RenameEngine().clean_filename(input) == expected
```

### Application Layer (mocked dependencies)

```python
# tests/unit/application/test_scanner_service.py

class TestScannerService:
    def test_scan_adds_new_files(self, container, audio_fixtures_dir):
        service = container.scanner_service
        session = service.scan_library(
            library_id=1,
            options=ScanOptions(scan_type="full"),
        )
        assert session.files_added == 5
        assert session.status == "completed"

    def test_incremental_skips_unchanged(self, container, audio_fixtures_dir):
        service = container.scanner_service
        service.scan_library(library_id=1, options=ScanOptions(scan_type="full"))
        session2 = service.scan_library(library_id=1, options=ScanOptions(scan_type="incremental"))
        assert session2.files_added == 0
        assert session2.files_skipped == 5

    def test_corrupt_file_logged_not_crashed(self, container, tmp_path):
        corrupt = tmp_path / "corrupt.flac"
        corrupt.write_bytes(b"not audio")
        session = container.scanner_service.scan_library(library_id=1, ...)
        assert session.files_errored == 1
        assert session.status == "completed"
```

## Integration Tests

### Database Round-Trip

```python
# tests/integration/test_database.py

class TestDatabase:
    def test_create_schema(self, test_db):
        """All tables exist after migration."""
        ...

    def test_track_upsert_and_query(self, container):
        track = Track(file_path="D:/test.flac", title="Test", ...)
        saved = container.track_repository.upsert(track)
        loaded = container.track_repository.get_by_id(saved.id)
        assert loaded.title == "Test"

    def test_batch_upsert_performance(self, container):
        """500 tracks upserted in < 1 second."""
        tracks = [make_track(i) for i in range(500)]
        start = time.monotonic()
        container.track_repository.upsert_batch(tracks)
        assert time.monotonic() - start < 1.0
```

### Scanner Integration

```python
# tests/integration/test_scanner.py

class TestScannerIntegration:
    def test_scans_mixed_format_directory(self, container, audio_fixtures_dir):
        session = container.scanner_service.scan_library(...)
        tracks = container.track_repository.get_by_library(1)
        codecs = {t.codec for t in tracks}
        assert codecs == {"flac", "mp3", "aac"}

    def test_reads_all_metadata_fields(self, container, audio_fixtures_dir):
        container.scanner_service.scan_library(...)
        track = container.track_repository.get_by_path("...flac")
        assert track.bitrate is not None
        assert track.sample_rate == 44100
        assert track.duration_ms > 0
```

### Rollback Integration

```python
# tests/integration/test_rollback.py

class TestRollback:
    def test_metadata_fix_rollback(self, container, sample_tracks):
        original_title = "Original Title"
        # Apply metadata fix
        container.operation_orchestrator.execute(
            OperationRequest(operation_type="metadata_fix", track_ids=[1], dry_run=False)
        )
        track = container.track_repository.get_by_id(1)
        assert track.title != original_title

        # Rollback
        container.rollback_service.rollback(operation_id=1)
        track = container.track_repository.get_by_id(1)
        assert track.title == original_title
```

## Mocking Strategy

| Dependency | Mock Approach |
|-----------|--------------|
| MusicBrainz API | `responses` library with fixture JSON |
| AcoustID API | `responses` library with fixture JSON |
| Chromaprint (`fpcalc`) | Mock `FingerprintGenerator` protocol |
| File system | `tmp_path` pytest fixture (real files) |
| Send2Trash | Mock `FileOperations.safe_delete` |
| FFmpeg | Mock `FFmpegProbe` for unit tests; real for integration |
| Qt GUI | `pytest-qt` for ViewModel tests only |

### HTTP Mocking Example

```python
import responses

@responses.activate
def test_musicbrainz_lookup(container):
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/recording/...",
        json=load_fixture("musicbrainz_recording.json"),
        status=200,
    )
    result = container.metadata_service.identify_track(track_id=1)
    assert result.mb_recording_id == "abc-123"
    assert result.confidence > 0.9
```

## CI Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -e ".[dev]"
      - run: python tests/fixtures/generate_audio.py
      - run: pytest --cov=vaultseek --cov-report=xml
      - run: mypy src/ --strict
      - run: ruff check src/ tests/
      - run: import-linter

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff import-linter
      - run: ruff check src/ tests/
      - run: lint-imports
```

## Code Quality Gates

| Tool | Config | Threshold |
|------|--------|-----------|
| `pytest` | `pyproject.toml` | All tests pass |
| `mypy` | `strict = true` | Zero errors |
| `ruff` | Default rules + `ANN` (annotations) | Zero warnings |
| `import-linter` | Layer contracts | Zero violations |
| `pytest-cov` | `--cov-fail-under=80` | ≥ 80% overall |
| Domain coverage | Per-module | ≥ 95% for `domain/` |

## Test Naming Convention

```python
def test_{what}_{condition}_{expected}():
    ...

# Examples:
def test_quality_scorer_flac_24bit_returns_100():
def test_scanner_corrupt_file_increments_error_count():
def test_rollback_metadata_fix_restores_original_title():
def test_rename_engine_scene_pattern_removes_release_group():
```

## Test Data Management

| Data | Storage | Regeneration |
|------|---------|-------------|
| Audio files | `tests/fixtures/audio/` (gitignored) | `generate_audio.py` in CI |
| API responses | `tests/fixtures/metadata/` (in repo) | Recorded manually once |
| Database | In-memory per test | `conftest.py` fixture |
| Config | `tests/fixtures/config/` (in repo) | Hand-written |

## Performance Tests

Marked with `@pytest.mark.performance`, excluded from default CI run:

```python
@pytest.mark.performance
def test_batch_upsert_10000_tracks_under_5_seconds(container):
    tracks = [make_track(i) for i in range(10_000)]
    start = time.monotonic()
    container.track_repository.upsert_batch(tracks)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0
```

Run manually: `pytest -m performance`

## Regression Tests

When a bug is fixed, a test is added:

```
tests/
└── regression/
    ├── test_issue_42_scene_rename.py
    └── test_issue_87_duplicate_remaster.py
```

Named after the issue number. Never deleted — permanent guard against regressions.
