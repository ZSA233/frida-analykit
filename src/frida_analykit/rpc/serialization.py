from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .handle_ref import HandleRef


@runtime_checkable
class SupportsHandleRef(Protocol):
    def to_handle_ref(self) -> HandleRef: ...


def serialize_rpc_argument(value: Any) -> Any:
    if isinstance(value, HandleRef):
        return value.to_rpc_arg()
    if isinstance(value, SupportsHandleRef):
        return value.to_handle_ref().to_rpc_arg()
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, bytes | str):
        return value
    if isinstance(value, Mapping):
        return {str(key): serialize_rpc_argument(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [serialize_rpc_argument(item) for item in value]
    return value
