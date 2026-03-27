from frida_analykit.rpc.handler.js_handle import JsHandle, Unset
from frida_analykit.rpc.message import RPCMessage, RPCMsgType, RPCPayload


class _FakeExportsSync:
    def __init__(self) -> None:
        self.enumerate_calls: list[tuple[str, str]] = []
        self.scope_del_calls: list[tuple[str, str]] = []

    def enumerate_obj_props(self, inst_id: str, scope_id: str) -> RPCPayload:
        self.enumerate_calls.append((inst_id, scope_id))
        return RPCPayload(
            message=RPCMessage.from_mapping(
                {
                    "type": RPCMsgType.ENUMERATE_OBJ_PROPS.value,
                    "data": {"props": [{}]},
                }
            )
        )

    def scope_del(self, inst_id: str, scope_id: str) -> None:
        self.scope_del_calls.append((inst_id, scope_id))


class _FakeScript:
    def __init__(self) -> None:
        self.exports_sync = _FakeExportsSync()


def test_child_property_handle_uses_parent_path_before_inst_id_is_assigned() -> None:
    script = _FakeScript()
    proc = JsHandle(
        "Process",
        script=script,
        inst_id="Process",
        props={"findModuleByName": Unset("function")},
    )

    child = proc.findModuleByName

    assert isinstance(child, JsHandle)
    assert str(child) == "Process/findModuleByName"
    assert script.exports_sync.enumerate_calls == [("Process/findModuleByName", "")]
