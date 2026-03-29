from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final, Iterable, Literal, Mapping

HANDLE_REF_MARKER: Final[str] = "__frida_analykit_handle_ref__"
_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

HandleRefKind = Literal["path", "scope"]


@dataclass(frozen=True, slots=True)
class HandleRef:
    kind: HandleRefKind
    segments: tuple[str, ...] = ()
    slot_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "path":
            if self.slot_id is not None:
                raise ValueError("path handle refs do not accept slot ids")
            if not self.segments:
                raise ValueError("path handle refs require at least one segment")
            return

        if self.slot_id is None:
            raise ValueError("scope handle refs require a slot id")

    @classmethod
    def from_seed_path(cls, path: str) -> "HandleRef":
        segments = tuple(part for part in path.split("/") if part)
        if not segments:
            raise ValueError("handle path must not be empty")
        return cls(kind="path", segments=segments)

    @classmethod
    def path(cls, segments: Iterable[str]) -> "HandleRef":
        items = tuple(str(item) for item in segments)
        if not items:
            raise ValueError("path handle refs require at least one segment")
        return cls(kind="path", segments=items)

    @classmethod
    def scope(cls, slot_id: str, *, segments: Iterable[str] = ()) -> "HandleRef":
        return cls(kind="scope", slot_id=slot_id, segments=tuple(str(item) for item in segments))

    @classmethod
    def from_rpc_arg(cls, value: Mapping[str, Any]) -> "HandleRef | None":
        marker = value.get(HANDLE_REF_MARKER)
        if marker not in {"path", "scope"}:
            return None
        segments = tuple(str(item) for item in value.get("segments", ()))
        if marker == "path":
            return cls.path(segments)
        slot_id = value.get("slot_id")
        if not isinstance(slot_id, str) or not slot_id:
            raise ValueError("scope handle refs require a non-empty slot_id")
        return cls.scope(slot_id, segments=segments)

    def child(self, segment: str) -> "HandleRef":
        return HandleRef(kind=self.kind, slot_id=self.slot_id, segments=self.segments + (str(segment),))

    @property
    def owns_scope_slot(self) -> bool:
        return self.kind == "scope" and not self.segments

    def to_rpc_arg(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            HANDLE_REF_MARKER: self.kind,
            "segments": list(self.segments),
        }
        if self.slot_id is not None:
            payload["slot_id"] = self.slot_id
        return payload

    def render(self) -> str:
        if self.kind == "path":
            return "/".join(self.segments)
        assert self.slot_id is not None
        base = f"scope[{self.slot_id}]"
        if not self.segments:
            return base
        return f"{base}/{'/'.join(self.segments)}"

    def to_js_expr(self) -> str:
        if self.kind == "path":
            root, *rest = self.segments
            expression = _root_segment_expr(root)
        else:
            assert self.slot_id is not None
            expression = self.slot_id
            rest = list(self.segments)
        for segment in rest:
            expression += _child_segment_expr(segment)
        return expression


def _root_segment_expr(segment: str) -> str:
    if _IDENTIFIER_RE.match(segment):
        return segment
    return f"globalThis[{json.dumps(segment, ensure_ascii=False)}]"


def _child_segment_expr(segment: str) -> str:
    if segment.isdigit():
        return f"[{segment}]"
    if _IDENTIFIER_RE.match(segment):
        return f".{segment}"
    return f"[{json.dumps(segment, ensure_ascii=False)}]"
