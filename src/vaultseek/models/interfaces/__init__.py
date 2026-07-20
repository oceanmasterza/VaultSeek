"""Protocol definitions for repositories, file I/O, and fingerprinting.

Application and infrastructure code depend on these protocols rather than
on each other's concrete implementations (dependency inversion).
:mod:`vaultseek.models.interfaces.fingerprint` is populated in Phase 5;
repository protocols expand as later phases need them (see
docs/architecture/07-roadmap.md).
"""
