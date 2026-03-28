from frida_analykit.rpc.message import (
    RPCMessage,
    RPCMsgBatch,
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
