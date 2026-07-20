"""Built-in Nicotine+ acquisition provider (skeleton)."""

from vaultseek.plugins.builtin.nicotine_plus.provider import NicotinePlusProvider
from vaultseek.plugins.builtin.nicotine_plus.rpc import (
    FakeRpcClient,
    NicotinePlusRpcClient,
    RpcDownloadState,
    RpcSearchHit,
    UnimplementedRpcClient,
)

__all__ = [
    "FakeRpcClient",
    "NicotinePlusProvider",
    "NicotinePlusRpcClient",
    "RpcDownloadState",
    "RpcSearchHit",
    "UnimplementedRpcClient",
]
