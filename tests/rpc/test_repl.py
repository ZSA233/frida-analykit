import os
import sys
import types

from frida_analykit.cli.common import _run_repl
from frida_analykit.repl import LazyJsHandleProxy, build_repl_namespace


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


class _FakeHandle:
    def __init__(self, path: str) -> None:
        self.path = path
        self.arch = "arm64"
        self.value_ = {"path": path}

    def __repr__(self) -> str:
        return f"<FakeHandle {self.path}>"

    def __str__(self) -> str:
        return self.path

    def __dir__(self) -> list[str]:
        return ["arch", "value_"]

    def __call__(self, *args):
        return (self.path, args)


class _FakeScript:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def jsh(self, path: str) -> _FakeHandle:
        self.calls.append(path)
        return _FakeHandle(path)


def test_build_repl_namespace_keeps_handles_lazy_until_first_use() -> None:
    script = _FakeScript()

    namespace = build_repl_namespace({"script": object()}, script=script, global_names=["Process"])
    proc = namespace["Process"]

    assert isinstance(proc, LazyJsHandleProxy)
    assert script.calls == []
    assert str(proc) == "Process"
    assert script.calls == []
    assert proc.arch == "arm64"
    assert proc.value_ == {"path": "Process"}
    assert script.calls == ["Process"]


def test_build_repl_namespace_materializes_on_dir() -> None:
    script = _FakeScript()

    namespace = build_repl_namespace({"script": object()}, script=script, global_names=["Process"])
    proc = namespace["Process"]

    assert "arch" in dir(proc)
    assert script.calls == ["Process"]


def test_build_repl_namespace_rejects_invalid_names() -> None:
    script = _FakeScript()

    try:
        build_repl_namespace({"script": object()}, script=script, global_names=["Process/value"])
    except ValueError as exc:
        assert "valid Python identifier" in str(exc)
    else:  # pragma: no cover - assertion fallback
        raise AssertionError("expected invalid repl global to fail")

    try:
        build_repl_namespace({"script": object()}, script=script, global_names=["script"])
    except ValueError as exc:
        assert "conflicts" in str(exc)
    else:  # pragma: no cover - assertion fallback
        raise AssertionError("expected conflicting repl global to fail")

    try:
        build_repl_namespace({"script": object()}, script=script, global_names=["Process", "Process"])
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:  # pragma: no cover - assertion fallback
        raise AssertionError("expected duplicate repl global to fail")
