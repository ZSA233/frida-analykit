from __future__ import annotations

from dataclasses import dataclass, field
from importlib.resources import files
from typing import Final

_DOC_FILES: Final[dict[str, str]] = {
    "index": "index.md",
    "config": "config.md",
    "quickstart": "quickstart.md",
    "workflow": "workflow.md",
    "tools": "tools.md",
    "recovery": "recovery.md",
}


@dataclass(slots=True)
class MCPDocsProvider:
    _cache: dict[str, str] = field(default_factory=dict)

    def resource_index_markdown(self) -> str:
        return self._read("index")

    def resource_workflow_markdown(self) -> str:
        return self._read("workflow")

    def resource_config_markdown(self) -> str:
        return self._read("config")

    def resource_quickstart_markdown(self) -> str:
        return self._read("quickstart")

    def resource_tools_markdown(self) -> str:
        return self._read("tools")

    def resource_recovery_markdown(self) -> str:
        return self._read("recovery")

    def _read(self, name: str) -> str:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        filename = _DOC_FILES[name]
        content = files("frida_analykit.resources").joinpath("mcp_docs").joinpath(filename).read_text(encoding="utf-8")
        self._cache[name] = content
        return content
