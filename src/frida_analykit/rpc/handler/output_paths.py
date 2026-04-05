from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path


_SEPARATOR_RE = re.compile(r"[\\/]+")
_UNSAFE_CHAR_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DOT_ONLY_RE = re.compile(r"^\.+$")


def safe_name(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    cleaned = _SEPARATOR_RE.sub("_", raw)
    cleaned = _UNSAFE_CHAR_RE.sub("_", cleaned)
    cleaned = cleaned.strip("_")
    if not cleaned or _DOT_ONLY_RE.fullmatch(cleaned):
        return "default"
    return cleaned


@dataclass(frozen=True, slots=True)
class OutputLeaf:
    root: Path
    directory: Path
    tag: str
    effective_tag: str
    relative_dir: str


def resolve_configured_output_root(
    *,
    configured_root: Path | None,
    agent_datadir: Path | None,
    fallback_child: str,
    missing_message: str,
) -> Path:
    root = configured_root
    if root is None and agent_datadir is not None:
        root = agent_datadir / fallback_child
    if root is None:
        raise RuntimeError(missing_message)
    return root.resolve()

def resolve_output_leaf(root: Path, tag: str) -> OutputLeaf:
    resolved_root = root.resolve()
    raw_tag = tag.strip()
    effective_tag = safe_name(raw_tag) if raw_tag else ""
    directory = (resolved_root / effective_tag).resolve() if effective_tag else resolved_root
    _ensure_within_root(resolved_root, directory, label="output leaf")
    relative_dir = effective_tag if effective_tag else ""
    return OutputLeaf(
        root=resolved_root,
        directory=directory,
        tag=raw_tag,
        effective_tag=effective_tag,
        relative_dir=relative_dir,
    )


def reset_output_leaf(leaf: OutputLeaf, *, cleanup_patterns: tuple[str, ...] = ()) -> None:
    leaf.root.mkdir(parents=True, exist_ok=True)
    if leaf.effective_tag:
        if leaf.directory.exists():
            shutil.rmtree(leaf.directory)
        leaf.directory.mkdir(parents=True, exist_ok=True)
        return

    leaf.directory.mkdir(parents=True, exist_ok=True)
    for pattern in cleanup_patterns:
        for path in leaf.directory.glob(pattern):
            if path.is_file():
                path.unlink()


def _ensure_within_root(root: Path, candidate: Path, *, label: str) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes configured root {root}: {candidate}") from exc
