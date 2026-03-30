from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, Field


class RPCMsgType(str, Enum):
    SCOPE_CALL = "SCOPE_CALL"
    SCOPE_EVAL = "SCOPE_EVAL"
    SCOPE_GET = "SCOPE_GET"
    ENUMERATE_OBJ_PROPS = "ENUMERATE_OBJ_PROPS"
    BATCH = "BATCH"
    INIT_CONFIG = "INIT_CONFIG"
    SAVE_FILE = "SAVE_FILE"
    DEX_DUMP_BEGIN = "DEX_DUMP_BEGIN"
    DUMP_DEX_FILE = "DUMP_DEX_FILE"
    DEX_DUMP_END = "DEX_DUMP_END"
    SSL_SECRET = "SSL_SECRET"
    PROGRESSING = "PROGRESSING"


class RPCBatchSource(str, Enum):
    DEX_DUMP_FILES = "DEX_DUMP_FILES"


class RPCMsgInitConfig(BaseModel):
    OnRPC: bool = True
    LogCollapse: bool = False
    BatchMaxBytes: int = 8 * 1024 * 1024


class RPCMsgError(BaseModel):
    pass


class RPCMsgScopeCall(BaseModel):
    id: str
    type: str
    result: Any | None = None
    has_result: bool = False


class RPCMsgScopeEval(BaseModel):
    id: str
    type: str
    result: Any | None = None
    has_result: bool = False


class RPCMsgScopeGet(BaseModel):
    value: Any | None = None
    has_value: bool = False


class RPCMsgEnumerateObjProps(BaseModel):
    props: list[dict[str, Any]] = Field(default_factory=list)


class RPCMsgSaveFile(BaseModel):
    source: str
    filepath: str
    mode: str


class RPCMsgDexDumpBegin(BaseModel):
    transfer_id: str
    tag: str = ""
    dump_dir: str | None = None
    expected_count: int
    total_bytes: int = 0
    max_batch_bytes: int = 8 * 1024 * 1024


class RPCMsgDexDumpFileInfo(BaseModel):
    name: str
    base: str
    size: int
    loader: str
    loader_class: str
    output_name: str


class RPCMsgDumpDexFile(BaseModel):
    transfer_id: str
    tag: str = ""
    info: RPCMsgDexDumpFileInfo


class RPCMsgDexDumpEnd(BaseModel):
    transfer_id: str
    tag: str = ""
    expected_count: int
    received_count: int
    total_bytes: int = 0


class RPCMsgSSLSecret(BaseModel):
    tag: str
    label: str
    client_random: str
    secret: str


class RPCErrorMessage(BaseModel):
    message: str | None = None
    stack: str | None = None


class RPCMsgProgressing(BaseModel):
    tag: str
    id: int
    step: int
    time: int
    extra: dict[str, Any] = Field(default_factory=dict)
    error: RPCErrorMessage | None = None


class RPCMessage(BaseModel):
    type: RPCMsgType
    tid: int | None = None
    source: str | None = None
    data: BaseModel = Field(default_factory=RPCMsgError)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RPCMessage":
        msg_type = RPCMsgType(payload["type"])
        data_model = _MESSAGE_TYPES.get(msg_type, RPCMsgError)
        data = data_model.model_validate(payload.get("data") or {})
        return cls(
            type=msg_type,
            tid=payload.get("tid"),
            source=payload.get("source"),
            data=data,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "tid": self.tid,
            "source": self.source,
            "data": self.data.model_dump(mode="json"),
        }


class RPCMsgBatch(BaseModel):
    message_list: list[RPCMessage]
    data_sizes: list[int]

    @classmethod
    def model_validate(cls, obj: Any, *args, **kwargs):  # type: ignore[override]
        if isinstance(obj, Mapping):
            obj = dict(obj)
            obj["message_list"] = [
                RPCMessage.from_mapping(item) if not isinstance(item, RPCMessage) else item
                for item in obj.get("message_list", [])
            ]
        return super().model_validate(obj, *args, **kwargs)


_MESSAGE_TYPES: dict[RPCMsgType, type[BaseModel]] = {
    RPCMsgType.SCOPE_CALL: RPCMsgScopeCall,
    RPCMsgType.SCOPE_EVAL: RPCMsgScopeEval,
    RPCMsgType.SCOPE_GET: RPCMsgScopeGet,
    RPCMsgType.ENUMERATE_OBJ_PROPS: RPCMsgEnumerateObjProps,
    RPCMsgType.BATCH: RPCMsgBatch,
    RPCMsgType.INIT_CONFIG: RPCMsgInitConfig,
    RPCMsgType.SAVE_FILE: RPCMsgSaveFile,
    RPCMsgType.DEX_DUMP_BEGIN: RPCMsgDexDumpBegin,
    RPCMsgType.DUMP_DEX_FILE: RPCMsgDumpDexFile,
    RPCMsgType.DEX_DUMP_END: RPCMsgDexDumpEnd,
    RPCMsgType.SSL_SECRET: RPCMsgSSLSecret,
    RPCMsgType.PROGRESSING: RPCMsgProgressing,
}


@dataclass
class RPCPayload:
    message: RPCMessage
    data: bytes | None = None

    def __str__(self) -> str:
        length = len(self.data) if self.data else 0
        if self.message.type == RPCMsgType.BATCH:
            return f"<{self.message.type.value}({self.message.source})[{len(self.message.data.message_list)}]: {length}>"
        if self.message.source:
            return f"<{self.message.type.value}({self.message.source}): {length}>"
        return f"<{self.message.type.value}: {length}>"


def unpack_batch_payload(payload: RPCPayload) -> list[RPCPayload]:
    message = payload.message
    if message.type != RPCMsgType.BATCH:
        return [payload]

    batch = message.data
    assert isinstance(batch, RPCMsgBatch)
    output: list[RPCPayload] = []
    offset = 0
    for item, data_size in zip(batch.message_list, batch.data_sizes):
        chunk = None
        if data_size > 0 and payload.data is not None:
            chunk = payload.data[offset : offset + data_size]
            offset += data_size
        output.append(RPCPayload(message=item, data=chunk))
    return output
