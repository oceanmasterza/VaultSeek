# 08 — Performance Strategy (v3)

> **Updated**: Incorporates single-writer DB queue, ProcessPool/ThreadPool split, generator streaming.
> See [12-pipeline-engine-v3.md](12-pipeline-engine-v3.md).

## Target

VaultSeek must comfortably manage libraries of **1,000,000+ tracks** on a typical enthusiast PC (8-core CPU, 16 GB RAM, NVMe SSD).

## Performance Budgets

| Operation | Target (1M tracks) | Strategy |
|-----------|-------------------|----------|
| Full scan (metadata only) | < 4 hours | ProcessPool hash + single DB writer |
| Full fingerprint pass | < 24 hours | ProcessPool fpcalc, background job |
| Incremental scan | < 5 minutes | mtime comparison, skip unchanged |
| Dashboard load | < 500 ms | Materialized `library_stats` |
| Library browse (page) | < 200 ms | Indexed query + pagination |
| Duplicate detection | < 30 minutes | Generator streaming + batch grouping |
| Metadata (1000 tracks) | < 30 minutes | Rate-limited + cache-first cascade |

## Execution Engine

### Three-Tier Worker Model

```
ProcessPoolExecutor          ThreadPoolExecutor         DatabaseWriter
(CPU-bound)                  (I/O-bound)                (single thread)
─────────────────           ─────────────────           ──────────────
HashWorker                   ScannerWorker              ← WriteDTO queue
FingerprintWorker            MetadataWorker             batch 5K–10K rows
AudioParserWorker            ArtworkWorker              one transaction
QualityScorerWorker          OrganizerWorker
                             MediaServerWorker
                             DuplicateWorker
```

**Critical rule**: Only `DatabaseWriter` executes INSERT/UPDATE/DELETE. All other components are read-only against SQLite or queue writes.

### Why Not ThreadPool for Everything (v2 gap)

Python's GIL limits CPU-bound work to ~1 core in threads:

| Task | Bound | Pool |
|------|-------|------|
| SHA-256 hash | CPU | **ProcessPool** |
| Chromaprint (fpcalc) | CPU | **ProcessPool** |
| Mutagen tag decode | CPU | **ProcessPool** |
| Directory walk | I/O | ThreadPool |
| HTTP (MusicBrainz) | I/O | ThreadPool |
| File move/rename | I/O | ThreadPool |

Expected hash throughput: ~70 files/sec on 8-core (ProcessPool) vs ~10 files/sec (ThreadPool).

## Database Writer Queue

```python
# Workers emit DTOs — never touch SQLite for writes
db_writer_queue.put(WriteDTO(
    table="tracks",
    operation="upsert",
    rows=[...5000 rows...],
    job_id=job.id,
))
```

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Batch size | 5,000–10,000 rows | Amortize transaction overhead |
| Flush interval | 500 ms | Don't hold partial batches too long |
| Queue type | `queue.Queue` | Thread-safe, unbounded |
| Writer count | **1** | SQLite single-writer constraint |

### Write Contention Elimination

Without single writer (v2 risk):
- 8 workers × small commits = constant `database is locked`
- Retry storms degrade throughput 10×

With single writer (v3):
- Workers never block on write lock
- One large transaction per batch = optimal WAL append

## Generator-Based Streaming

Never load full library into RAM:

```python
for batch in iter_tracks(conn, library_id, batch_size=1_000):
    process_batch(batch)    # Fixed memory regardless of library size
```

Mandatory for: duplicate detection, reports, quality rescoring, incremental scan diff.

## SQLite Tuning

```python
PRAGMAS = [
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA cache_size = -64000",              # 64 MB page cache
    "PRAGMA temp_store = MEMORY",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA mmap_size = {adaptive}",           # min(30GB, 25% available RAM)
]
```

**UUID storage**: BLOB(16) not TEXT(36) — saves ~20 MB per indexed column at 1M rows.

## Memory Budget

| Component | Max | Notes |
|-----------|-----|-------|
| ProcessPool workers | 8 × 50 MB = 400 MB | One file per process |
| DB writer buffer | ~50 MB | 10K rows × ~5 KB |
| DB page cache | 64 MB | PRAGMA |
| Generator batches | 10 MB | 1K tracks in flight |
| GUI | 10 MB | Virtual scrolling |
| **Total peak** | **~550 MB** | Well within 16 GB |

Child processes in ProcessPool do not hold SQLite connections — results returned as dicts, parent enqueues WriteDTO.

## Fingerprint Skip Logic

If `file_identity.file_size + file_modified` unchanged → skip hash, fingerprint, and metadata workers. At 1M tracks with 1% daily change, incremental processing touches ~10K files not 1M.

## Network Rate Limiting

Adaptive token bucket per provider. Cache-first cascade — see [12-pipeline-engine-v3.md § Metadata Provider Cascade](12-pipeline-engine-v3.md).

## GUI Responsiveness

- Workers publish to **EventBus**; `QtEventBridge` marshals to main thread
- Progress updates throttled to 4/sec
- Job Monitor polls `jobs` table (read-only, WAL concurrent)
- No database writes on main thread

## Profiling

Built-in metrics logged per pipeline stage:

```
Scan session: 52,341 files in 2h 14m
  Hash (ProcessPool):     1h 02m  (14.0 files/sec, 8 cores)
  DB writes:              4m 12s  (12 batches × ~4400 rows)
  Skipped (unchanged):    41,203
  Fingerprint queue:     11,138 pending jobs
```

## Hardware Recommendations

| Library Size | CPU | RAM | Disk |
|-------------|-----|-----|------|
| < 50K | 4-core | 8 GB | SSD |
| 50K–500K | 8-core | 16 GB | NVMe |
| 500K–1M+ | 8+ core | 32 GB | NVMe |

ProcessPool benefits scale with physical cores — more cores = faster hash/fingerprint passes.
