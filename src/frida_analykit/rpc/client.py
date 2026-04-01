from __future__ import annotations

from collections.abc import Mapping, Sequence
from threading import Lock
from typing import Any, Final, TypeVar

from frida.core import Script
from pydantic import BaseModel, ValidationError

from .exports import ScriptExportsAsyncWrapper, ScriptExportsSyncWrapper, make_rpc_response
from .handle_ref import HandleRef
from .message import (
    RPCMsgEnumerateObjProps,
    RPCMsgScopeCall,
    RPCMsgScopeEval,
    RPCMsgScopeGet,
    RPCPayload,
)
from .protocol import (
    RPC_REQUIRED_FEATURES,
    RPC_RUNTIME_INFO_EXPORT,
    RPC_PROTOCOL_VERSION,
    RPCCompatibilityError,
    RPCRuntimeInfo,
)
from .serialization import serialize_rpc_argument

TModel = TypeVar("TModel", bound=BaseModel)
_PROTOCOL_GUARDED_EXPORTS: Final[frozenset[str]] = frozenset(
    {
        "enumerate_obj_props",
        "scope_call",
        "scope_call_async",
        "scope_eval",
        "scope_eval_async",
        "scope_get",
        "scope_get_async",
        "scope_save",
        "scope_clear",
        "scope_del",
    }
)


class RPCValueUnavailableError(RuntimeError):
    pass


class RPCClient:
    def __init__(self, script: Script, *, scope_id: str, interactive: bool = False) -> None:
        self.scope_id = scope_id
        self.interactive = interactive
        self._compat_lock = Lock()
        self._runtime_info: RPCRuntimeInfo | None = None
        self._compat_error: RPCCompatibilityError | None = None
        self._rpc_exports_sync = ScriptExportsSyncWrapper(
            script,
            serializer=serialize_rpc_argument,
            response_adapter=make_rpc_response,
            before_call=self._before_sync_export_call,
        )
        self._rpc_exports_async = ScriptExportsAsyncWrapper(
            script,
            serializer=serialize_rpc_argument,
            response_adapter=make_rpc_response,
            before_call=self._before_async_export_call,
        )

    def call(self, ref: HandleRef, args: Sequence[Any]) -> RPCMsgScopeCall:
        return self._expect_model(
            self._rpc_exports_sync.scope_call(ref.to_rpc_arg(), list(args), self.scope_id),
            RPCMsgScopeCall,
        )

    async def call_async(self, ref: HandleRef, args: Sequence[Any]) -> RPCMsgScopeCall:
        return self._expect_model(
            await self._rpc_exports_async.scope_call_async(ref.to_rpc_arg(), list(args), self.scope_id),
            RPCMsgScopeCall,
        )

    def eval(self, source: str) -> RPCMsgScopeEval:
        return self._expect_model(self._rpc_exports_sync.scope_eval(source, self.scope_id), RPCMsgScopeEval)

    async def eval_async(self, source: str) -> RPCMsgScopeEval:
        return self._expect_model(
            await self._rpc_exports_async.scope_eval_async(source, self.scope_id),
            RPCMsgScopeEval,
        )

    def get_value(self, ref: HandleRef) -> Any:
        data = self._expect_model(self._rpc_exports_sync.scope_get(ref.to_rpc_arg(), self.scope_id), RPCMsgScopeGet)
        if not data.has_value:
            raise RPCValueUnavailableError(
                "handle value is not available synchronously; use resolve_async() or continue chaining"
            )
        return data.value

    async def get_value_async(self, ref: HandleRef) -> Any:
        data = self._expect_model(
            await self._rpc_exports_async.scope_get_async(ref.to_rpc_arg(), self.scope_id),
            RPCMsgScopeGet,
        )
        if not data.has_value:
            raise RPCValueUnavailableError("handle value is not serializable across the RPC bridge")
        return data.value

    def enumerate_props(self, refs: HandleRef | Sequence[HandleRef]) -> RPCMsgEnumerateObjProps:
        payload = refs.to_rpc_arg() if isinstance(refs, HandleRef) else [item.to_rpc_arg() for item in refs]
        return self._expect_model(
            self._rpc_exports_sync.enumerate_obj_props(payload, self.scope_id),
            RPCMsgEnumerateObjProps,
        )

    async def enumerate_props_async(self, refs: HandleRef | Sequence[HandleRef]) -> RPCMsgEnumerateObjProps:
        payload = refs.to_rpc_arg() if isinstance(refs, HandleRef) else [item.to_rpc_arg() for item in refs]
        return self._expect_model(
            await self._rpc_exports_async.enumerate_obj_props(payload, self.scope_id),
            RPCMsgEnumerateObjProps,
        )

    def release_scope_ref(self, ref: HandleRef) -> None:
        if not ref.owns_scope_slot:
            return
        self._rpc_exports_sync.scope_del(ref.to_rpc_arg(), self.scope_id)

    async def release_scope_ref_async(self, ref: HandleRef) -> None:
        if not ref.owns_scope_slot:
            return
        await self._rpc_exports_async.scope_del(ref.to_rpc_arg(), self.scope_id)

    def clear_scope_sync(self) -> None:
        self._rpc_exports_sync.scope_clear(self.scope_id)

    async def clear_scope(self) -> None:
        await self._rpc_exports_async.scope_clear(self.scope_id)

    @staticmethod
    def _expect_model(response: Any, model_type: type[TModel]) -> TModel:
        if not isinstance(response, RPCPayload):
            raise TypeError(f"expected RPCPayload, got {type(response)!r}")
        data = response.message.data
        if not isinstance(data, model_type):
            raise TypeError(f"expected {model_type.__name__}, got {type(data)!r}")
        return data

    def _before_sync_export_call(self, name: str) -> None:
        if name in _PROTOCOL_GUARDED_EXPORTS:
            self.ensure_runtime_compatible()

    async def _before_async_export_call(self, name: str) -> None:
        if name in _PROTOCOL_GUARDED_EXPORTS:
            await self.ensure_runtime_compatible_async()

    def ensure_runtime_compatible(self) -> RPCRuntimeInfo:
        if self._runtime_info is not None:
            return self._runtime_info
        if self._compat_error is not None:
            raise self._compat_error

        with self._compat_lock:
            if self._runtime_info is not None:
                return self._runtime_info
            if self._compat_error is not None:
                raise self._compat_error

            exports = set(self._rpc_exports_sync._list_exports())
            if RPC_RUNTIME_INFO_EXPORT not in exports:
                error = self._build_runtime_mismatch_error(
                    "loaded `_agent.js` does not expose `rpcRuntimeInfo()` and cannot negotiate the structured HandleRef protocol"
                )
                self._compat_error = error
                raise error

            info = self._validate_runtime_info(self._rpc_exports_sync.rpc_runtime_info())
            self._runtime_info = info
            return info

    async def ensure_runtime_compatible_async(self) -> RPCRuntimeInfo:
        if self._runtime_info is not None:
            return self._runtime_info
        if self._compat_error is not None:
            raise self._compat_error

        exports = set(await self._rpc_exports_async._list_exports())
        if RPC_RUNTIME_INFO_EXPORT not in exports:
            error = self._build_runtime_mismatch_error(
                "loaded `_agent.js` does not expose `rpcRuntimeInfo()` and cannot negotiate the structured HandleRef protocol"
            )
            self._compat_error = error
            raise error

        info = self._validate_runtime_info(await self._rpc_exports_async.rpc_runtime_info())
        self._runtime_info = info
        return info

    def _validate_runtime_info(self, payload: Any) -> RPCRuntimeInfo:
        if not isinstance(payload, Mapping):
            raise self._build_runtime_mismatch_error(
                f"`rpcRuntimeInfo()` returned {type(payload)!r} instead of a mapping"
            )

        try:
            info = RPCRuntimeInfo.model_validate(payload)
        except ValidationError as exc:
            raise self._build_runtime_mismatch_error(
                f"`rpcRuntimeInfo()` returned an invalid payload: {exc}"
            ) from exc
        if info.protocol_version != RPC_PROTOCOL_VERSION:
            raise self._build_runtime_mismatch_error(
                "loaded `_agent.js` speaks RPC protocol "
                f"{info.protocol_version}, but this Python runtime requires {RPC_PROTOCOL_VERSION}"
            )

        missing_features = sorted(RPC_REQUIRED_FEATURES.difference(info.features))
        if missing_features:
            raise self._build_runtime_mismatch_error(
                "loaded `_agent.js` is missing required RPC features: " + ", ".join(missing_features)
            )
        return info

    @staticmethod
    def _build_runtime_mismatch_error(detail: str) -> RPCCompatibilityError:
        return RPCCompatibilityError(
            "RPC runtime mismatch: "
            f"{detail}. Please rebuild `_agent.js` with the local packed runtime from this checkout "
            "(for example: `npm pack ./packages/frida-analykit-agent`, install that tarball into the workspace, "
            "then rerun `frida-analykit build --install`)."
        )
