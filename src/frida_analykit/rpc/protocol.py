from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field

RPC_PROTOCOL_VERSION: Final[int] = 2
RPC_RUNTIME_INFO_EXPORT: Final[str] = "rpc_runtime_info"
RPC_REQUIRED_FEATURES: Final[frozenset[str]] = frozenset({"handle_ref", "async_scope"})


class RPCCompatibilityError(RuntimeError):
    """Raised when Python and agent runtime RPC protocols do not match."""


class RPCRuntimeInfo(BaseModel):
    protocol_version: int
    features: frozenset[str] = Field(default_factory=frozenset)

