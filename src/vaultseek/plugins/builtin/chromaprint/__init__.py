"""Built-in Chromaprint fingerprint generation (no AcoustID HTTP yet)."""

from vaultseek.plugins.builtin.chromaprint.provider import (
    ChromaprintFingerprintProvider,
    generate_chromaprint,
)

__all__ = ["ChromaprintFingerprintProvider", "generate_chromaprint"]
