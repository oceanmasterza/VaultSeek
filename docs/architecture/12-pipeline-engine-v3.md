# 12 — Pipeline Engine & Scalability Refinements (v3)

> **Status**: Approved refinements to v2. Incorporate before Phase 1.
> **Date**: 2026-07-15
> **Supersedes**: Specific v2 patterns noted below; v2 remains authoritative for all unmentioned areas.

This document evaluates the latest scalability recommendations, records adopt/reject decisions with justification, and specifies the execution engine architecture that was implicit but underspecified in v2.

---

## Recommendation Evaluation

| # | Recommendation | Verdict | Action |
|---|---------------|---------|--------|
| 1 | Dedicated single-writer DB queue | **Adopt** | Critical gap in v2 — workers must not write to SQLite directly |
| 2 | Dual-pool execution (ProcessPool + ThreadPool) | **Adopt** | v2 used ThreadPool only; GIL limits CPU-bound work |
| 3 | SQLAlchemy Core + generator streaming | **Adopt** | Core already chosen; add explicit generator/cursor policy |
| 4 | Adaptive rate limiting + local-first cascade | **Adopt with modification** | Two cascades: enrichment vs identification (see §4) |
| 5 | Event bus for GUI decoupling | **Adopt** | Complements Qt signals; workers publish events, GUI bridge subscribes |
| 6 | UUID as BINARY(16) blobs | **Adopt with modification** | Use **UUID v7** stored as BLOB(16), not v4 — see §6 |
| 7 | Batch writes 5,000–10,000 rows | **Adopt** | Increase from v2's 500; single writer makes this safe |
| 8 | PRAGMA mmap up to 30 GB | **Modify** | Use adaptive mmap cap, not fixed 30 GB — see §7 |
| 9 | Folder layout (`models/`, `db/`, `services/`, `workers/`) | **Adopt** | Clearer layer names; update folder layout doc |
| 10 | Composite confidence scoring formula | **Adopt** | Supplements per-field provider confidence — see §8 |
| 11 | Rules engine AST evaluation | **Adopt** | Implementation approach for JSON/YAML rules |
| 12 | Navidrome read/**write** SQLite sync | **Reject write** | Read-only DB access; mutations via Subsonic API only — see §9 |
| 13 | "Audio Parser" in ProcessPool | **Adopt** | Mutagen tag read + FFmpeg probe for CPU-heavy decode paths |

---

## Execution Engine Architecture

MusicVault is a **local data pipeline**, not a conventional desktop app. The execution model has four distinct tiers:

```
┌─────────────────────────────────────────────────────────────────┐
│                     GUI (PySide6 / MVVM)                        │
│   Dashboard │ Library │ Review Queue │ Duplicate Viewer │ Jobs  │
└────────────────────────────┬────────────────────────────────────┘
                             │ Commands ↓   ↑ Events (via Event Bus)
┌────────────────────────────v────────────────────────────────────┐
│              SERVICE LAYER (services/)                           │
│  JobQueueManager │ RulesEngine │ ConfidenceEngine │ Arbitrator  │
│  StagingEngine │ RollbackService │ PluginController │ EventBus  │
└────────────────────────────┬────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          v                  v                  v
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
│  ProcessPool    │ │  ThreadPool     │ │  DB Writer Thread   │
│  (CPU-bound)    │ │  (I/O-bound)    │ │  (single writer)    │
│                 │ │                 │ │                     │
│  HashWorker     │ │  ScannerWorker  │ │  queue.Queue ← DTOs │
│  FingerprintW.  │ │  MetadataWorker │ │  batch 5K–10K rows  │
│  AudioParser    │ │  ArtworkWorker  │ │  one txn per batch  │
│  QualityScorer  │ │  OrganizerWorker│ │                     │
│                 │ │  MediaServerW.  │ │                     │
└────────┬────────┘ └────────┬────────┘ └──────────┬──────────┘
         │                   │                      │
         └───────────────────┴──────────────────────┘
                             │
                    WriteDTO / JobResult
                             │
                             v
                    SQLAlchemy Core → SQLite (WAL)
```

### Tier 1: ProcessPoolExecutor (CPU-Bound)

Bypasses the GIL. Used for:

| Worker | Work |
|--------|------|
| `HashWorker` | SHA-256 content hashing |
| `FingerprintWorker` | Chromaprint via fpcalc |
| `AudioParserWorker` | Mutagen tag extraction, FFmpeg probe for bit depth/sample rate |
| `QualityScorerWorker` | Batch quality score calculation |

```python
# Worker processes receive serialized job payload, return result dict
# No SQLite connection in child processes — results go to DB writer queue
def hash_worker_main(payload: dict) -> dict:
    file_path = payload["file_path"]
    digest = compute_sha256(file_path)
    return {"track_id": payload["track_id"], "content_hash_sha256": digest}
```

**Rule**: Child processes never open SQLite connections. They return DTOs to the parent, which enqueues them for the DB writer.

### Tier 2: ThreadPoolExecutor (I/O-Bound)

Used for:

| Worker | Work |
|--------|------|
| `ScannerWorker` | Directory walking, file stat, mtime comparison |
| `MetadataWorker` | HTTP to MusicBrainz, Discogs, AcoustID |
| `ArtworkWorker` | HTTP to Cover Art Archive, Discogs |
| `OrganizerWorker` | File move/rename (Send2Trash) |
| `MediaServerWorker` | Subsonic API, Navidrome DB read (read-only) |
| `DuplicateWorker` | DB reads + in-memory grouping (I/O + light CPU) |

Network workers use adaptive token-bucket rate limiters (see §4).

### Tier 3: Database Writer Thread (Single Writer)

**This was missing from v2 and is the most important addition.**

All workers emit `WriteDTO` objects to a thread-safe `queue.Queue`. One dedicated daemon thread is the **only** component that executes INSERT/UPDATE/DELETE:

```python
@dataclass(frozen=True)
class WriteDTO:
    table: str
    operation: Literal["upsert", "insert", "update", "delete"]
    rows: list[dict[str, Any]]      # Up to 10,000 rows per DTO
    job_id: UUID | None             # Link to job completion

class DatabaseWriter:
    """Single-threaded batch writer. The only SQLite writer in the application."""

    BATCH_SIZE = 5_000
    FLUSH_INTERVAL_MS = 500         # Flush partial batch after 500ms idle

    def __init__(self, engine: Engine, inbound: queue.Queue[WriteDTO]) -> None:
        self._engine = engine
        self._inbound = inbound
        self._buffer: list[WriteDTO] = []

    def run(self) -> None:
        while not self._shutdown.is_set():
            try:
                dto = self._inbound.get(timeout=0.5)
                self._buffer.append(dto)
                if self._count_buffered_rows() >= self.BATCH_SIZE:
                    self._flush()
            except queue.Empty:
                if self._buffer:
                    self._flush()

    def _flush(self) -> None:
        with self._engine.begin() as conn:
            for dto in self._buffer:
                stmt = build_upsert(dto.table, dto.rows)
                conn.execute(stmt, dto.rows)
        self._buffer.clear()
```

**Why this matters**: With 8 workers each trying to write, SQLite returns `database is locked` constantly. WAL allows concurrent readers but still **one writer at a time**. Serializing writes through one thread with large batches is faster than many threads fighting for the lock with small commits.

**Job status updates** also go through the DB writer queue — workers never touch `jobs` table directly.

### Tier 4: Job Dispatcher

Unchanged from v2 — claims jobs from SQLite (read-only query), assigns to appropriate pool, marks completion via DB writer queue.

---

## Risk: SQLite Write Contention — **CRITICAL** (new)

**Problem**: v2 allowed repositories to be called from any worker thread. At scale with 8+ concurrent workers, write lock contention causes pipeline stalls and `database is locked` errors.

**Solution**: Dedicated DB writer thread (§ Tier 3). Workers are read-only against SQLite (WAL concurrent reads) or use in-memory state. All mutations go through `WriteDTO` queue.

**Read path**: Multiple threads may execute SELECT concurrently under WAL.
**Write path**: Exactly one thread.

---

## Risk: Python GIL — **CRITICAL** (new)

**Problem**: v2 assigned HashWorker and FingerprintWorker to ThreadPoolExecutor. SHA-256 and Chromaprint are CPU-bound; the GIL limits these to ~1 core.

**Solution**: ProcessPoolExecutor for CPU-bound workers. Expect near-linear scaling up to physical core count.

| Cores | ThreadPool hash throughput | ProcessPool hash throughput (est.) |
|-------|---------------------------|-----------------------------------|
| 4 | ~10 files/sec | ~35 files/sec |
| 8 | ~10 files/sec | ~70 files/sec |
| 16 | ~10 files/sec | ~120 files/sec |

Fingerprint (fpcalc) benefits similarly — each invocation is a subprocess, but orchestrating 8 fpcalc calls from one GIL-bound thread still serializes Python-side bookkeeping.

---

## Generator-Based Streaming

All bulk operations must stream — never load 1M rows into RAM:

```python
def iter_tracks(
    conn: Connection,
    library_id: UUID,
    *,
    batch_size: int = 1_000,
) -> Generator[list[TrackRow], None, None]:
    """Server-side cursor streaming. Yields fixed-size batches."""
    offset = 0
    while True:
        rows = conn.execute(
            select(tracks.c.id, tracks.c.file_path, ...).where(
                tracks.c.library_id == uuid_to_blob(library_id)
            ).limit(batch_size).offset(offset)
        ).fetchall()
        if not rows:
            break
        yield [TrackRow.from_tuple(r) for r in rows]
        offset += batch_size
```

**Mandatory for**:
- Duplicate detection scans
- Full-library quality rescoring
- Report generation
- Incremental scan comparison (stream DB paths vs filesystem walk)

---

## Metadata Provider Cascade (Revised)

v2 listed MusicBrainz first globally. The correct approach is **two cascades** depending on context:

### Identification Cascade (unknown track, no MBID)

Used when fingerprint or tags don't resolve to a known entity:

```
1. Local SQLite cache (prior lookup for this fingerprint/hash)
2. AcoustID API (fingerprint → MBID)
3. MusicBrainz API (MBID lookup)
4. MusicBrainz API (tag search)
5. Discogs API (search)
6. Local embedded tags (low confidence baseline)
7. Filename parser (last resort)
```

### Enrichment Cascade (known track, filling gaps)

Used when track has MBID but missing fields (year, composer, etc.):

```
1. Local embedded tags
2. Local SQLite cache
3. MusicBrainz API
4. Discogs API
5. Cover Art Archive (artwork only)
```

**Key principle**: Never hit the network if local data is sufficient. Cache TTL: fingerprint lookups 30 days, tag searches 7 days.

### Rate Limiting

```python
class AdaptiveRateLimiter:
    """Token bucket with exponential backoff on HTTP 429."""

    def __init__(self, rate: float, burst: int = 1) -> None:
        self._rate = rate          # tokens per second
        self._burst = burst
        self._backoff_until: float = 0

    def acquire(self) -> None:
        # Block until token available; respect backoff_until after 429
        ...
```

| Provider | Default Rate |
|----------|-------------|
| MusicBrainz | 1.0 req/sec |
| AcoustID | 3.0 req/sec |
| Discogs | 1.0 req/sec |
| Cover Art Archive | 5.0 req/sec |

---

## UUID Storage: v7 as BLOB(16)

### v2 → v3 Change

| Aspect | v2 | v3 |
|--------|----|----|
| Version | UUID v7 | UUID v7 (unchanged) |
| Storage | TEXT (36 chars) | **BLOB(16)** (16 bytes) |
| Index size per key | 36 bytes | 16 bytes |
| Application boundary | `UUID` object | `UUID` object (convert at repository) |

### Why v7, Not v4 (as recommended)

The recommendation specifies UUIDv4. We keep **v7** because:

- Both v4 and v7 generate offline without DB roundtrip (parallel worker requirement satisfied)
- v7 is time-ordered → better B-tree insert locality for append-heavy scan workloads
- v7 embeds timestamp → useful for debugging job/entity creation order

v4's only advantage is wider library support in older code. Python's standard library
gained `uuid.uuid7()` natively in **3.14** (verified against the official CPython
changelog — an earlier draft of this document incorrectly said 3.12). MusicVault now
requires Python **3.14+** for exactly this reason: it is the single most-used primitive
in the entire schema, and a native stdlib implementation avoids taking on a third-party
dependency for it. See [07-roadmap.md](07-roadmap.md) Phase 1 notes for how this was
discovered.

### Conversion

```python
def uuid_to_blob(u: UUID) -> bytes:
    return u.bytes

def blob_to_uuid(b: bytes) -> UUID:
    return UUID(bytes=b)

# SQLAlchemy Core column
Column("id", LargeBinary(16), primary_key=True)
```

All SQL queries use blob form. Domain dataclasses use `UUID`. Repository boundary converts.

**Index savings at 1M tracks**: ~(36−16) × 1M = ~20 MB per indexed column. Meaningful at scale.

---

## PRAGMA Configuration (Revised)

```python
def configure_sqlite_connection(conn: Connection) -> None:
    conn.execute(text("PRAGMA journal_mode = WAL"))
    conn.execute(text("PRAGMA synchronous = NORMAL"))
    conn.execute(text("PRAGMA cache_size = -64000"))          # 64 MB page cache
    conn.execute(text("PRAGMA temp_store = MEMORY"))
    conn.execute(text("PRAGMA foreign_keys = ON"))
    conn.execute(text("PRAGMA busy_timeout = 5000"))

    # Adaptive mmap — NOT fixed 30 GB
    available_ram = psutil.virtual_memory().available
    mmap_cap = min(30 * 1024**3, int(available_ram * 0.25))
    mmap_cap = max(mmap_cap, 256 * 1024**2)                   # Floor 256 MB
    conn.execute(text(f"PRAGMA mmap_size = {mmap_cap}"))
```

**Why not fixed 30 GB**: `mmap_size` sets an upper bound on memory-mapped I/O, not allocated RAM. Setting 30 GB on a 16 GB system doesn't allocate 30 GB, but it can cause the OS to overcommit virtual address space and degrade performance on memory-constrained systems. Adaptive sizing is safer.

---

## Composite Confidence Scoring

Supplements per-field provider confidence from the `MetadataArbitrator`.

For overall match quality (routing to review vs auto-approve), compute a weighted composite:

```
Score = (w₁ × acoustid_match)
      + (w₂ × duration_delta_score)
      + (w₃ × tag_similarity)
      + (w₄ × track_count_match)
      + (w₅ × provider_confidence)
```

Default weights (configurable):

| Factor | Weight | Calculation |
|--------|--------|-------------|
| AcoustID match | 0.35 | AcoustID score directly (0.0–1.0) |
| Duration delta | 0.20 | 1.0 if ≤2s diff, linear decay to 0 at 10s |
| Tag similarity | 0.20 | RapidFuzz ratio on artist+title |
| Track count match | 0.10 | 1.0 if album track count matches |
| Provider confidence | 0.15 | Best provider's overall confidence |

**Routing**:
- `Score ≥ 0.90` → auto-approve (if no duplicate flags)
- `Score < 0.90` → Review Queue

Per-field confidence (from arbitrator) still stored in `metadata_confidence` for the Review UI to show field-level provenance. Composite score stored on `tracks.overall_confidence`.

---

## Rules Engine — AST Evaluation

Rules stored as JSON/YAML, parsed into an AST, evaluated per track:

```yaml
name: "Archive MP3 when FLAC exists"
priority: 10
conditions:
  all:
    - field: codec
      operator: eq
      value: mp3
    - field: has_lossless_duplicate
      operator: eq
      value: true
actions:
  - action_type: move_to_zone
    parameters: { zone: archive }
  - action_type: flag_review
    parameters: { reason: "MP3 archived — FLAC copy exists" }
requires_approval: false
```

> **Correction (Phase 3)**: This example originally used `op`/`type`/`params` as
> the YAML keys. That doesn't match the actual `RuleCondition`/`RuleAction`
> dataclass fields defined in [10-revision-v2.md](10-revision-v2.md#rules-engine)
> (`operator`, `action_type`, `parameters`) and implemented in
> `models/value_objects/rule_condition.py` / `rule_action.py`. Corrected to keep
> the documented example consistent with the code.

```python
@dataclass(frozen=True)
class RuleNode:
    """AST node — either a condition leaf or a logical group."""
    pass

@dataclass(frozen=True)
class ConditionLeaf(RuleNode):
    field: str
    operator: str
    value: Any

@dataclass(frozen=True)
class AndNode(RuleNode):
    children: list[RuleNode]

@dataclass(frozen=True)
class OrNode(RuleNode):
    children: list[RuleNode]

class RulesEngine:
    def parse(self, rule_dict: dict) -> RuleNode: ...
    def evaluate(self, node: RuleNode, context: TrackContext) -> bool: ...
    def run_rules(self, track: Track) -> list[RuleAction]:
        for rule in self._rules_sorted_by_priority:
            if self.evaluate(rule.ast_root, TrackContext.from_track(track)):
                yield from rule.actions
```

Rules evaluate after metadata identification, before organize. `requires_approval: true` creates a review item instead of executing.

---

## Event Bus

Decouples workers from GUI. Workers publish domain events; a `QtEventBridge` (main thread) subscribes and emits Qt signals.

```python
@dataclass(frozen=True)
class DomainEvent:
    timestamp: datetime

@dataclass(frozen=True)
class JobProgressEvent(DomainEvent):
    job_id: UUID
    job_type: JobType
    progress: float
    detail: str

@dataclass(frozen=True)
class ReviewItemAddedEvent(DomainEvent):
    item_id: UUID
    review_type: ReviewType

class EventBus:
    def publish(self, event: DomainEvent) -> None: ...
    def subscribe(self, event_type: type[DomainEvent], handler: Callable) -> None: ...
```

```python
class QtEventBridge(QObject):
    """Runs on main thread. Subscribes to EventBus, emits Qt signals."""
    job_progress = Signal(JobProgressEvent)
    review_item_added = Signal(ReviewItemAddedEvent)

    def _on_job_progress(self, event: JobProgressEvent) -> None:
        self.job_progress.emit(event)   # Already on main thread via queued connection
```

ViewModels connect to Qt signals, never to EventBus directly.

---

## Navidrome Integration — Read-Only DB

**Adopt**: Direct read of `navidrome.db` for bulk queries.
**Reject**: Direct write to `navidrome.db`.

| Operation | Method |
|-----------|--------|
| List albums missing artwork | Read navidrome.db |
| Detect duplicate artists | Read navidrome.db |
| Find broken paths | Read navidrome.db |
| Get scan status | Read navidrome.db |
| Trigger rescan | **Subsonic API** (`startScan` endpoint) |
| Update tags | **Subsonic API** or user action in Navidrome UI |

Writing directly to Navidrome's SQLite bypasses its in-memory cache and business logic, risks schema corruption on Navidrome upgrade, and may require Navidrome restart. Read-only access is safe and sufficient for validation.

```python
# Safe
conn = sqlite3.connect(f"file:{navidrome_db}?mode=ro", uri=True)

# Never in MusicVault
conn.execute("UPDATE album SET ...")  # FORBIDDEN
```

---

## Revised Folder Layout (v3)

Cleaner layer names aligned with the pipeline model:

```
src/musicvault/
├── models/          # Pure dataclasses (was domain/entities + value_objects)
├── core/            # DI, config, logging, paths, exceptions, event_bus
├── db/              # SQLAlchemy Core tables, engine, migrations, repositories
├── services/        # JobQueueManager, RulesEngine, Arbitrator, Staging, Rollback
├── workers/         # All worker implementations (process + thread pools)
├── plugins/         # Plugin protocols + builtins
└── gui/             # PySide6 views, viewmodels, widgets
```

Domain services (`QualityScorer`, `DuplicateMatcher`, etc.) move to `models/services/` — pure logic, no I/O.

Import boundary rules unchanged; paths updated.

---

## v2 → v3 Summary

| Component | v2 | v3 |
|-----------|----|----|
| DB writes | Any worker via repository | **Single DB writer thread** |
| CPU workers | ThreadPool | **ProcessPool** |
| I/O workers | ThreadPool | ThreadPool (unchanged) |
| UUID storage | TEXT(36) | **BLOB(16)** |
| Batch size | 500 rows | **5,000–10,000 rows** |
| mmap | Fixed 256 MB | **Adaptive** (256 MB – 25% RAM, max 30 GB) |
| GUI communication | Callbacks + signals | **Event bus + Qt bridge** |
| Metadata cascade | Single order | **Identification vs enrichment** |
| Confidence | Per-field only | **Per-field + composite score** |
| Rules | JSON conditions | **JSON/YAML → AST** |
| Navidrome DB | Read-only | Read-only (**write rejected**) |
| Folder layout | domain/, application/, infrastructure/ | **models/, services/, db/, workers/** |

---

## Phase 1 Impact

These refinements are documentation-only. Phase 1 scaffold uses the v3 folder layout:

```
src/musicvault/
├── models/
├── core/          # includes event_bus.py stub
├── db/
├── services/
├── workers/
├── plugins/
└── gui/
```

DB writer queue and ProcessPool are Phase 4+ implementations. Phase 1 creates empty packages with correct structure.
