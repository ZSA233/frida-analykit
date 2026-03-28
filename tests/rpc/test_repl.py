import os
import sys
import types

from frida_analykit.cli.common import _run_repl


def test_run_repl_uses_async_ptpython_embed(monkeypatch) -> None:
    calls: dict[str, object] = {}

    async def fake_coroutine() -> None:
        calls["awaited"] = True

    def fake_embed(globals_ns, locals_ns, **kwargs):
        calls["globals"] = globals_ns
        calls["locals"] = locals_ns
        calls["kwargs"] = kwargs
        return fake_coroutine()

    ptpython_module = types.ModuleType("ptpython")
    repl_module = types.ModuleType("ptpython.repl")
    repl_module.embed = fake_embed

    monkeypatch.setitem(sys.modules, "ptpython", ptpython_module)
    monkeypatch.setitem(sys.modules, "ptpython.repl", repl_module)
    monkeypatch.delenv("REPL", raising=False)

    _run_repl({"script": "demo"})

    assert os.environ["REPL"] == "1"
    assert calls["awaited"] is True
    assert calls["locals"] == {"script": "demo"}
    assert calls["kwargs"] == {"return_asyncio_coroutine": True}
