"""UUIDv7 generation and BLOB(16) conversion helpers.

Every primary and foreign key in the schema is a UUIDv7, generated
client-side — so a worker process never needs a database round trip just
to obtain an ID — and stored as a 16-byte BLOB rather than a 36-character
TEXT string, roughly halving index size at scale. See
docs/architecture/12-pipeline-engine-v3.md ("UUID Storage: v7 as BLOB(16)")
for the full rationale, including why v7 was kept over the v4 originally
suggested in an external review: v7 is time-ordered, giving good B-tree
insert locality for this schema's append-mostly workload.

Python 3.14+ provides :func:`uuid.uuid7` in the stdlib. On 3.12/3.13 we
use a small RFC 9562 polyfill so the app can stay on a **single** runtime
that also has Windows wheels for ``shazamio-core`` (≤3.12 today).
"""

from __future__ import annotations

import os
import threading
import time
from uuid import UUID

try:
    from uuid import uuid7 as _stdlib_uuid7
except ImportError:  # Python < 3.14
    _stdlib_uuid7 = None

_UUID_BLOB_LENGTH = 16

# Monotonic state for the polyfill (same-ms counter in rand_a, 12 bits).
_polyfill_lock = threading.Lock()
_polyfill_last_ms = -1
_polyfill_seq = 0


def generate_uuid7() -> UUID:
    """Generate a new time-ordered UUIDv7 for use as a primary key."""
    if _stdlib_uuid7 is not None:
        return _stdlib_uuid7()
    return _uuid7_polyfill()


# Public alias so call sites / tests can ``from vaultseek.db.uuid_utils import uuid7``.
uuid7 = generate_uuid7


def _uuid7_polyfill() -> UUID:
    """RFC 9562 §5.7 UUIDv7 with a same-millisecond monotonic counter.

    Keeping ``rand_a`` as an incrementing sequence means IDs generated in a
    tight loop remain sortable — important for job claim ordering and tests.
    """
    global _polyfill_last_ms, _polyfill_seq

    with _polyfill_lock:
        timestamp_ms = time.time_ns() // 1_000_000
        if timestamp_ms == _polyfill_last_ms:
            _polyfill_seq += 1
            if _polyfill_seq >= 0x1000:
                # Counter overflow — wait for the next millisecond.
                while time.time_ns() // 1_000_000 <= _polyfill_last_ms:
                    time.sleep(0.00005)
                timestamp_ms = time.time_ns() // 1_000_000
                _polyfill_seq = 0
        else:
            _polyfill_seq = 0
        _polyfill_last_ms = timestamp_ms
        seq = _polyfill_seq

    timestamp_ms &= 0xFFFFFFFFFFFF
    buf = bytearray(16)
    buf[0] = (timestamp_ms >> 40) & 0xFF
    buf[1] = (timestamp_ms >> 32) & 0xFF
    buf[2] = (timestamp_ms >> 24) & 0xFF
    buf[3] = (timestamp_ms >> 16) & 0xFF
    buf[4] = (timestamp_ms >> 8) & 0xFF
    buf[5] = timestamp_ms & 0xFF
    # version 7 + 12-bit sequence (sortable within the same ms)
    buf[6] = ((seq >> 8) & 0x0F) | 0x70
    buf[7] = seq & 0xFF
    # variant + 62 bits of randomness
    rand = os.urandom(8)
    buf[8] = (rand[0] & 0x3F) | 0x80
    buf[9:16] = rand[1:8]
    return UUID(bytes=bytes(buf))


def uuid_to_blob(value: UUID) -> bytes:
    """Convert a UUID to its 16-byte binary form for a BLOB(16) column."""
    return value.bytes


def blob_to_uuid(value: bytes) -> UUID:
    """Convert a BLOB(16) column value back into a UUID.

    Raises:
        ValueError: if ``value`` is not exactly 16 bytes.
    """
    if len(value) != _UUID_BLOB_LENGTH:
        raise ValueError(f"Expected {_UUID_BLOB_LENGTH} bytes for a UUID BLOB, got {len(value)}.")
    return UUID(bytes=value)
