"""Built-in Nicotine+ acquisition provider."""

from vaultseek.plugins.builtin.nicotine_plus.provider import NicotinePlusProvider
from vaultseek.plugins.builtin.nicotine_plus.rpc import (
    FakeRpcClient,
    LocalSocketRpcClient,
    NicotinePlusRpcClient,
    RpcDownloadState,
    RpcSearchHit,
    UnimplementedRpcClient,
)

__all__ = [
    "FakeRpcClient",
    "LocalSocketRpcClient",
    "NicotinePlusProvider",
    "NicotinePlusRpcClient",
    "RpcDownloadState",
    "RpcSearchHit",
    "UnimplementedRpcClient",
]
