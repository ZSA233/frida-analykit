from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import (
    CAPABILITY_IMPORTS,
    CAPABILITY_RETAIN_EXPORTS,
    ENV_TYPES_FILENAME,
    TEMPLATE_CAPABILITIES,
    TEMPLATE_HINTS,
)
from .models import BootstrapKind, QuickCapability, QuickTemplate


@dataclass(frozen=True, slots=True)
class PreparedBootstrap:
    kind: BootstrapKind
    source_text: str | None = None
    original_path: Path | None = None
    workspace_filename: str | None = None
    signature_path: str | None = None
    signature_hash: str | None = None

    @property
    def import_path(self) -> str | None:
        if self.workspace_filename is None:
            return None
        return f"./{self.workspace_filename}"


def render_index_source(
    *,
    template: QuickTemplate,
    capabilities: tuple[QuickCapability, ...],
    bootstrap: PreparedBootstrap,
) -> str:
    lines = [
        f'/// <reference path="./{ENV_TYPES_FILENAME}" />',
        "// Generated quick entry for frida-analykit MCP.",
        f"// Template preset: {template}",
        f'import "{CAPABILITY_IMPORTS["rpc"]}"',
    ]
    retain_bindings: list[str] = []
    for capability in capabilities:
        if capability == "rpc":
            continue
        retain_binding = CAPABILITY_RETAIN_EXPORTS[capability]
        lines.append(f'import {{ {retain_binding} }} from "{CAPABILITY_IMPORTS[capability]}"')
        retain_bindings.append(retain_binding)
    if bootstrap.kind == "path" and bootstrap.import_path is not None:
        lines.extend(
            [
                "",
                "// Separate bootstrap file copied from bootstrap_path.",
                f'import "{bootstrap.import_path}"',
            ]
        )
    bootstrap_source_lines = render_inlined_bootstrap_source(bootstrap)
    if bootstrap_source_lines:
        lines.append("")
        lines.extend(bootstrap_source_lines)
    if retain_bindings:
        lines.append("")
        lines.extend(f"void {retain_binding}" for retain_binding in retain_bindings)
    lines.extend(["", f"// {TEMPLATE_HINTS[template]}", ""])
    return "\n".join(lines) + "\n"


def resolve_capabilities(
    template: QuickTemplate,
    requested: list[QuickCapability],
) -> tuple[QuickCapability, ...]:
    ordered: list[QuickCapability] = []
    for capability in ("rpc", *TEMPLATE_CAPABILITIES[template], *requested):
        if capability not in ordered:
            ordered.append(capability)
    return tuple(ordered)


def render_inlined_bootstrap_source(bootstrap: PreparedBootstrap) -> list[str]:
    if bootstrap.kind != "source" or bootstrap.source_text is None:
        return []
    source_lines = bootstrap.source_text.rstrip("\n").splitlines()
    if not source_lines:
        return []
    return [
        "// Begin inlined bootstrap_source.",
        *source_lines,
        "// End inlined bootstrap_source.",
    ]
