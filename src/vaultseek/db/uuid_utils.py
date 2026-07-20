"""UUIDv7 generation and BLOB(16) conversion helpers.

Every primary and foreign key in the schema is a UUIDv7, generated
client-side — so a worker process never needs a database round trip just
to obtain an ID — and stored as a 16-byte BLOB rather than a 36-character
TEXT string, roughly halving index size at scale. See
docs/architecture/12-pipeline-engine-v3.md ("UUID Storage: v7 as BLOB(16)")
for the full rationale, including why v7 was kept over the v4 originally
suggested in an external review: v7 is time-ordered, giving good B-tree
insert locality for this schema's append-mostly workload.
"""

from __future__ import annotations

from uuid import UUID, uuid7

_UUID_BLOB_LENGTH = 16


def generate_uuid7() -> UUID:
    """Generate a new time-ordered UUIDv7 for use as a primary key."""
    return uuid7()


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
