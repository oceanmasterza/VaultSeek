# 08 — Performance Strategy

## Target

MusicVault must comfortably manage libraries of **1,000,000+ tracks** on a typical enthusiast PC (8-core CPU, 16 GB RAM, NVMe SSD).

## Performance Budgets

| Operation | Target (1M tracks) | Strategy |
|-----------|-------------------|----------|
| Full scan (first time) | < 8 hours | 8-thread pool, batch DB writes |
| Incremental scan | < 5 minutes | mtime comparison, skip unchanged |
| Dashboard load | < 500 ms | Materialized `library_stats` table |
| Library browse (page) | < 200 ms | Indexed query + pagination (100 rows) |
| Search (title/artist) | < 1 second | SQLite FTS5 or indexed LIKE |
| Duplicate detection | < 30 minutes | Batch fingerprint comparison |
| Metadata fix (1000 tracks) | < 30 minutes | Rate-limited API + cache |
| Report generation | < 60 seconds | Streaming write, no full load |

## Scanning Performance

### Thread Pool Architecture

```
Main Thread
  └── ScannerService.scan_library()
        ├── FileWalker.walk()           → list of file paths (single thread)
        └── ThreadPoolExecutor(8)
              ├── Worker 1: read → hash → fingerprint → queue
              ├── Worker 2: read → hash → fingerprint → queue
              ├── ...
              └── DB Writer Thread: batch upsert every 500 tracks
```

### Optimizations

1. **Batch database writes** — accumulate 500 tracks in memory, single `upsert_batch()` transaction
2. **Skip unchanged files** — compare `file_modified` mtime against DB; skip if identical
3. **Lazy fingerprinting** — fingerprint only on first scan or when requested; not during incremental
4. **Extension pre-filter** — `FileWalker` checks extension before stat call
5. **Memory-mapped I/O** — SQLite `mmap_size = 256MB` for read-heavy queries
6. **No artwork extraction during scan** — only detect presence (`has_embedded_art` boolean); extract on demand

### Throughput Estimates

| Step | Per-file time | Notes |
|------|--------------|-------|
| File stat + extension check | ~0.1 ms | Filesystem metadata |
| Mutagen metadata read | ~5–20 ms | Depends on format, tag size |
| SHA256 hash (50 MB FLAC) | ~100 ms | Disk I/O bound |
| Chromaprint generate | ~500 ms | CPU bound |
| DB upsert (batch of 500) | ~50 ms amortized | Per file in batch |

**Without fingerprinting**: ~50 files/second → 1M tracks in ~5.5 hours
**With fingerprinting**: ~1.5 files/second → 1M tracks in ~7.7 days (run as background task)

Fingerprinting is **decoupled** from scanning — it runs as a separate background job after the initial scan.

## Database Performance

### SQLite Tuning

```python
ENGINE_OPTIONS = {
    "connect_args": {
        "check_same_thread": False,
    },
    "pool_size": 5,
    "max_overflow": 10,
}

PRAGMAS = [
    "PRAGMA journal_mode = WAL",       # Concurrent reads during writes
    "PRAGMA synchronous = NORMAL",     # Balance safety and speed
    "PRAGMA cache_size = -64000",      # 64 MB page cache
    "PRAGMA mmap_size = 268435456",    # 256 MB mmap
    "PRAGMA temp_store = MEMORY",      # Temp tables in RAM
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",      # Wait 5s on lock contention
]
```

### Query Optimization

| Pattern | Technique |
|---------|-----------|
| Paginated track list | `LIMIT/OFFSET` with indexed `ORDER BY` |
| Full-text search | SQLite FTS5 virtual table synced with `tracks` |
| Dashboard stats | Pre-computed `library_stats` row, refreshed after scan |
| Duplicate detection | Load fingerprints into memory, hash-group in Python |
| Artist album count | Denormalized `album_count` on `artists` table |
| Format breakdown | JSON column in `library_stats`, computed during scan |

### FTS5 for Search

```sql
CREATE VIRTUAL TABLE tracks_fts USING fts5(
    title, artist_name, album_title,
    content='tracks',
    content_rowid='id',
    tokenize='porter unicode61'
);
```

Synced via triggers on `tracks` INSERT/UPDATE/DELETE. Sub-second search across 1M tracks.

### Connection Management

- **Read connections**: Pool of 5, used by GUI queries and reports
- **Write connection**: Single dedicated connection for scan writes and operations
- **WAL mode**: Readers never block writers

## Memory Management

### Budget

| Component | Max Memory | Strategy |
|-----------|-----------|----------|
| Thread pool workers | 8 × 50 MB = 400 MB | One file in memory per worker |
| DB page cache | 64 MB | SQLite PRAGMA |
| Fingerprint batch | 100 MB | Process in chunks of 10,000 |
| GUI track table | 10 MB | Virtual scrolling, 100 rows loaded |
| Artwork cache | 200 MB | LRU eviction, disk-backed |
| **Total peak** | **~800 MB** | Well within 16 GB systems |

### Rules

1. Never load all tracks into memory — always paginate
2. Stream report generation — write rows as fetched, don't build full dataset
3. Fingerprint comparison uses on-disk cache, not in-memory dict of 1M entries
4. Artwork bytes stored on disk (`cache/artwork/`), not in SQLite BLOBs (except small embedded art)

## Caching Strategy

### Three-Tier Cache

```
L1: In-memory LRU (hot data, session lifetime)
  → Last 1000 track DTOs, active library stats

L2: Disk cache (warm data, TTL-based)
  → MusicBrainz responses (7 days)
  → AcoustID lookups (30 days)
  → Artwork images (30 days)
  → Fingerprint data (permanent)

L3: Database (cold data, permanent)
  → All track metadata, fingerprints, hashes
```

### Cache Invalidation

| Event | Invalidation |
|-------|-------------|
| Scan completes | L1 stats cleared; L2 unaffected; L3 updated |
| Metadata fix applied | L1 track DTOs cleared; L3 updated |
| Config change | L1 organize rules refreshed |
| Plugin config change | L2 API cache cleared for that plugin |

## Duplicate Detection at Scale

### Algorithm (1M tracks)

```
Phase 1: Hash grouping (O(n))
  → SELECT hash_value, GROUP BY → exact duplicates
  → ~seconds for 3M hash rows

Phase 2: MBID grouping (O(n))
  → SELECT mb_recording_id, GROUP BY → same recording
  → ~seconds for 1M tracks

Phase 3: AcoustID grouping (O(n))
  → SELECT acoustid_id, GROUP BY → fingerprint matches
  → ~seconds for 1M fingerprints

Phase 4: Fuzzy matching (O(n log n))
  → Load fingerprints not matched in phases 1-3
  → Sort by duration, compare neighbors within ±2s
  → Chromaprint similarity > 0.85 → duplicate
  → ~minutes for remaining unmatched tracks
```

Phases 1–3 handle ~95% of duplicates in seconds. Phase 4 is the expensive step, run only on unmatched tracks.

## Network Performance

### API Rate Limits

| API | Limit | MusicVault Policy |
|-----|-------|-------------------|
| MusicBrainz | 1 req/sec | 1 req/sec (respect) |
| AcoustID | 3 req/sec | 3 req/sec |
| Cover Art Archive | No limit | 5 req/sec (polite) |
| Navidrome | Server-dependent | 2 req/sec default |

### Batching

- Metadata identification queues tracks, processes sequentially with rate limiting
- User can pause/resume identification queue
- Estimated time shown: "Identifying 50,000 tracks ≈ 14 hours"

## GUI Responsiveness

### Rules for 60 FPS UI

1. No database query on main thread — ever
2. Table models use `fetchMore()` — load 100 rows at a time
3. Images loaded asynchronously via `QThreadPool` + `QPixmap` cache
4. Progress updates throttled to 4/second (250 ms minimum interval)
5. Heavy computations (duplicate detection, report gen) show modal progress dialog

### Virtual Scrolling

`TrackTable` with 1M tracks:

```python
class TrackTableModel(QAbstractTableModel):
    PAGE_SIZE = 100

    def rowCount(self, parent):
        return self._total_count  # 1,000,000

    def data(self, index, role):
        row = index.row()
        if row not in self._cache:
            self._fetch_page(row // self.PAGE_SIZE)
        return self._cache[row].get(role)
```

Only 100–200 rows in memory at any time. Page fetches run in worker thread.

## Profiling & Monitoring

### Built-in Metrics

Logged after each major operation:

```
Scan complete: 52,341 files in 18m 32s (47.1 files/sec)
  Metadata read: 12m 10s (avg 14ms/file)
  Hash compute: 4m 22s (avg 5ms/file)
  DB write: 1m 45s (avg 2ms/file)
  Skipped (unchanged): 41,203
```

### Development Profiling

- `cProfile` integration behind `--profile` CLI flag
- Loguru structured logging with `duration_ms` field
- SQLite `EXPLAIN QUERY PLAN` for slow query detection in debug log

## Hardware Recommendations (User-Facing)

| Library Size | CPU | RAM | Disk | Notes |
|-------------|-----|-----|------|-------|
| < 50K tracks | 4-core | 8 GB | Any SSD | Runs smoothly on any modern PC |
| 50K–500K | 8-core | 16 GB | NVMe SSD | Recommended for fingerprinting |
| 500K–1M+ | 8+ core | 32 GB | NVMe SSD | Fingerprint as overnight background job |

## Future Optimizations (Post-1.0)

| Optimization | Trigger | Approach |
|-------------|---------|----------|
| PostgreSQL support | Multi-user / network | Optional backend for shared libraries |
| GPU fingerprinting | Chromaprint GPU port | If available, 10× fingerprint speed |
| Incremental duplicate detection | After incremental scan | Only check new/changed tracks |
| Parallel report generation | Report > 60 seconds | Chunk by artist, merge output |
| Database partitioning | > 2M tracks | Partition `tracks` by library_id |
