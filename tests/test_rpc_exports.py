from frida_analykit.rpc.exports import make_rpc_response
from frida_analykit.rpc.handler.js_handle import _safe_scope_del
from frida_analykit.rpc.message import RPCMsgEnumerateObjProps, RPCMsgType, RPCPayload


def test_make_rpc_response_wraps_mapping_into_rpc_payload() -> None:
    payload = make_rpc_response(
        {
            "type": RPCMsgType.ENUMERATE_OBJ_PROPS.value,
            "data": {
                "props": [{"use": "function"}],
            },
        }
    )

    assert isinstance(payload, RPCPayload)
    assert payload.message.type == RPCMsgType.ENUMERATE_OBJ_PROPS
    assert isinstance(payload.message.data, RPCMsgEnumerateObjProps)
    assert payload.message.data.props == [{"use": "function"}]


def test_make_rpc_response_leaves_non_rpc_values_untouched() -> None:
    assert make_rpc_response("pong") == "pong"
    assert make_rpc_response({"hello": "world"}) == {"hello": "world"}


def test_safe_scope_del_swallows_destroyed_script_errors() -> None:
    calls: list[tuple[str, str]] = []

    def broken_scope_del(inst_id: str, scope_id: str) -> None:
        calls.append((inst_id, scope_id))
        raise RuntimeError("script has been destroyed")

    _safe_scope_del(broken_scope_del, "inst", "scope")

    assert calls == [("inst", "scope")]
