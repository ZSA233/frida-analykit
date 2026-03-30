from frida_analykit.rpc.message import (
    RPCMessage,
    RPCMsgBatch,
    RPCMsgDexDumpBegin,
    RPCMsgSaveFile,
    RPCMsgScopeCall,
    RPCMsgType,
    RPCPayload,
    unpack_batch_payload,
)


def test_rpc_message_from_mapping_preserves_scope_result_flags() -> None:
    message = RPCMessage.from_mapping(
        {
            "type": RPCMsgType.SCOPE_CALL.value,
            "data": {
                "id": "slot-1",
                "type": "promise",
                "has_result": False,
            },
        }
    )

    assert isinstance(message.data, RPCMsgScopeCall)
    assert message.data.id == "slot-1"
    assert message.data.type == "promise"
    assert message.data.has_result is False


def test_unpack_batch_payload_splits_data_stream() -> None:
    payload = RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.BATCH,
            data=RPCMsgBatch(
                message_list=[
                    RPCMessage(type=RPCMsgType.SAVE_FILE, data=RPCMsgSaveFile(source="a", filepath="x", mode="wb")),
                    RPCMessage(type=RPCMsgType.SAVE_FILE, data=RPCMsgSaveFile(source="b", filepath="y", mode="wb")),
                ],
                data_sizes=[3, 2],
            ),
        ),
        data=b"abcde",
    )

    chunks = unpack_batch_payload(payload)

    assert [chunk.data for chunk in chunks] == [b"abc", b"de"]


def test_rpc_message_from_mapping_parses_dex_dump_begin() -> None:
    message = RPCMessage.from_mapping(
        {
            "type": RPCMsgType.DEX_DUMP_BEGIN.value,
            "data": {
                "transfer_id": "dex-1",
                "tag": "demo",
                "expected_count": 2,
                "total_bytes": 10,
                "max_batch_bytes": 4096,
            },
        }
    )

    assert isinstance(message.data, RPCMsgDexDumpBegin)
    assert message.data.transfer_id == "dex-1"
    assert message.data.expected_count == 2
    assert message.data.max_batch_bytes == 4096
