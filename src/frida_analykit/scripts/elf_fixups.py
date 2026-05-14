from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping


FIXUP_STAGE_ORDER: Final[tuple[str, ...]] = (
    "phdr-rebase",
    "dynamic-rebase",
    "dynsym-fixups",
    "relocation-fixups",
    "section-rebuild",
    "header-finalize",
)
FIXUP_STRATEGY_V2: Final[str] = "raw-to-fixed-staged-v2"
FIXUP_VERSION_V2: Final[int] = 2


class ElfFixupReplayError(RuntimeError):
    pass


@dataclass(slots=True)
class ElfFixupReplaySummary:
    raw_path: Path
    fixups_path: Path
    output_path: Path
    raw_size: int
    fixed_size: int
    stage_count: int
    patch_count: int
    compare_path: Path | None = None
    compare_matched: bool | None = None


def load_elf_fixups(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ElfFixupReplayError(f"failed to read fixups file `{path}`: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ElfFixupReplayError(f"failed to parse fixups file `{path}`: {exc}") from exc
    if not isinstance(payload, dict):
        raise ElfFixupReplayError(f"fixups file `{path}` must contain a JSON object")
    return payload


def replay_elf_fixups(
    raw: bytes,
    fixups: Mapping[str, object],
    *,
    check_before: bool = False,
) -> bytes:
    version = _require_int(fixups.get("version"), field="version")
    if version != FIXUP_VERSION_V2:
        raise ElfFixupReplayError(
            f"unsupported fixups version `{version}`; expected `{FIXUP_VERSION_V2}`"
        )

    strategy = _require_str(fixups.get("strategy"), field="strategy")
    if strategy != FIXUP_STRATEGY_V2:
        raise ElfFixupReplayError(
            f"unsupported fixups strategy `{strategy}`; expected `{FIXUP_STRATEGY_V2}`"
        )

    raw_size = _require_int(fixups.get("raw_size"), field="raw_size")
    fixed_size = _require_int(fixups.get("fixed_size"), field="fixed_size")
    if raw_size != len(raw):
        raise ElfFixupReplayError(
            f"raw_size mismatch: fixups expect `{raw_size}` bytes, got `{len(raw)}` bytes"
        )

    stages = _require_list(fixups.get("stages"), field="stages")
    stage_names: list[str] = []
    output = bytearray(raw)

    for stage_index, stage_item in enumerate(stages):
        stage = _require_mapping(stage_item, field=f"stages[{stage_index}]")
        stage_name = _require_str(stage.get("name"), field=f"stages[{stage_index}].name")
        stage_names.append(stage_name)

        patches = _require_list(stage.get("patches"), field=f"stages[{stage_index}].patches")
        for patch_index, patch_item in enumerate(patches):
            patch = _require_mapping(
                patch_item,
                field=f"stages[{stage_index}].patches[{patch_index}]",
            )
            patch_type = _require_str(
                patch.get("t"),
                field=f"stages[{stage_index}].patches[{patch_index}].t",
            )
            if patch_type == "f":
                _apply_field_patch(
                    output,
                    patch,
                    field=f"stages[{stage_index}].patches[{patch_index}]",
                    check_before=check_before,
                )
                continue
            if patch_type == "s":
                _apply_slot_patch(
                    output,
                    patch,
                    field=f"stages[{stage_index}].patches[{patch_index}]",
                    check_before=check_before,
                )
                continue
            if patch_type == "x":
                _apply_block_patch(
                    output,
                    patch,
                    field=f"stages[{stage_index}].patches[{patch_index}]",
                )
                continue
            raise ElfFixupReplayError(
                f"unsupported patch type `{patch_type}` at "
                f"`stages[{stage_index}].patches[{patch_index}]`"
            )

    if stage_names != list(FIXUP_STAGE_ORDER):
        raise ElfFixupReplayError(
            f"unexpected fixup stage order: {stage_names!r}; expected {list(FIXUP_STAGE_ORDER)!r}"
        )
    if len(output) != fixed_size:
        raise ElfFixupReplayError(
            f"fixed_size mismatch after replay: expected `{fixed_size}`, got `{len(output)}`"
        )
    return bytes(output)


def replay_elf_fixups_to_path(
    *,
    raw_path: Path,
    fixups_path: Path,
    output_path: Path,
    compare_path: Path | None = None,
    check_before: bool = False,
) -> ElfFixupReplaySummary:
    try:
        raw_bytes = raw_path.read_bytes()
    except OSError as exc:
        raise ElfFixupReplayError(f"failed to read raw ELF `{raw_path}`: {exc}") from exc

    fixups = load_elf_fixups(fixups_path)
    replayed = replay_elf_fixups(raw_bytes, fixups, check_before=check_before)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_bytes(replayed)
    except OSError as exc:
        raise ElfFixupReplayError(f"failed to write replayed ELF `{output_path}`: {exc}") from exc

    compare_matched: bool | None = None
    if compare_path is not None:
        try:
            compare_bytes = compare_path.read_bytes()
        except OSError as exc:
            raise ElfFixupReplayError(f"failed to read compare ELF `{compare_path}`: {exc}") from exc
        compare_matched = replayed == compare_bytes
        if not compare_matched:
            raise ElfFixupReplayError(
                f"replayed ELF `{output_path}` does not match compare file `{compare_path}`"
            )

    patch_count = 0
    stages = _require_list(fixups.get("stages"), field="stages")
    for stage_index, stage_item in enumerate(stages):
        stage = _require_mapping(stage_item, field=f"stages[{stage_index}]")
        patches = _require_list(stage.get("patches"), field=f"stages[{stage_index}].patches")
        patch_count += len(patches)

    return ElfFixupReplaySummary(
        raw_path=raw_path,
        fixups_path=fixups_path,
        output_path=output_path,
        raw_size=len(raw_bytes),
        fixed_size=len(replayed),
        stage_count=len(stages),
        patch_count=patch_count,
        compare_path=compare_path,
        compare_matched=compare_matched,
    )


def _apply_field_patch(
    output: bytearray,
    patch: Mapping[str, object],
    *,
    field: str,
    check_before: bool,
) -> None:
    width = _require_positive_int(patch.get("w"), field=f"{field}.w")
    offset = _require_non_negative_int(patch.get("o"), field=f"{field}.o")
    after = _scalar_hex_to_bytes(
        _require_str(patch.get("a"), field=f"{field}.a"),
        width=width,
        field=f"{field}.a",
    )
    _ensure_range(output, offset, width, field=field)

    if check_before:
        before = _scalar_hex_to_bytes(
            _require_str(patch.get("b"), field=f"{field}.b"),
            width=width,
            field=f"{field}.b",
        )
        _ensure_expected_before(output, offset, before, field=field)

    output[offset:offset + width] = after


def _apply_slot_patch(
    output: bytearray,
    patch: Mapping[str, object],
    *,
    field: str,
    check_before: bool,
) -> None:
    width = _require_positive_int(patch.get("w"), field=f"{field}.w")
    values = _require_list(patch.get("v"), field=f"{field}.v")
    for slot_index, slot_item in enumerate(values):
        slot_field = f"{field}.v[{slot_index}]"
        if not isinstance(slot_item, list) or len(slot_item) != 3:
            raise ElfFixupReplayError(
                f"`{slot_field}` must be a 3-item array of [offset, before, after]"
            )
        offset = _require_non_negative_int(slot_item[0], field=f"{slot_field}[0]")
        before_value = _require_str(slot_item[1], field=f"{slot_field}[1]")
        after_value = _require_str(slot_item[2], field=f"{slot_field}[2]")
        _ensure_range(output, offset, width, field=slot_field)

        if check_before:
            before = _scalar_hex_to_bytes(before_value, width=width, field=f"{slot_field}[1]")
            _ensure_expected_before(output, offset, before, field=slot_field)

        after = _scalar_hex_to_bytes(after_value, width=width, field=f"{slot_field}[2]")
        output[offset:offset + width] = after


def _apply_block_patch(
    output: bytearray,
    patch: Mapping[str, object],
    *,
    field: str,
) -> None:
    offset = _require_non_negative_int(patch.get("o"), field=f"{field}.o")
    replace_size = _require_non_negative_int(patch.get("r"), field=f"{field}.r")
    data = _hex_blob_to_bytes(
        _require_str(patch.get("x"), field=f"{field}.x"),
        field=f"{field}.x",
    )

    if replace_size == 0 and offset == len(output):
        output.extend(data)
        return

    if offset > len(output):
        raise ElfFixupReplayError(
            f"`{field}.o` points past the current output size: offset={offset}, size={len(output)}"
        )
    if offset + replace_size > len(output):
        raise ElfFixupReplayError(
            f"`{field}.r` extends past the current output size: "
            f"offset={offset}, replace_size={replace_size}, size={len(output)}"
        )
    output[offset:offset + replace_size] = data


def _require_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ElfFixupReplayError(f"`{field}` must be a JSON object")
    return value


def _require_list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ElfFixupReplayError(f"`{field}` must be a JSON array")
    return value


def _require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ElfFixupReplayError(f"`{field}` must be a string")
    return value


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ElfFixupReplayError(f"`{field}` must be an integer")
    return value


def _require_non_negative_int(value: object, *, field: str) -> int:
    integer = _require_int(value, field=field)
    if integer < 0:
        raise ElfFixupReplayError(f"`{field}` must be >= 0")
    return integer


def _require_positive_int(value: object, *, field: str) -> int:
    integer = _require_int(value, field=field)
    if integer <= 0:
        raise ElfFixupReplayError(f"`{field}` must be > 0")
    return integer


def _scalar_hex_to_bytes(value: str, *, width: int, field: str) -> bytes:
    if not value.startswith("0x"):
        raise ElfFixupReplayError(f"`{field}` must be a 0x-prefixed scalar hex value")
    hex_text = value[2:]
    if len(hex_text) > width * 2:
        raise ElfFixupReplayError(
            f"`{field}` does not fit in `{width}` bytes: {value!r}"
        )
    try:
        return bytes.fromhex(hex_text.rjust(width * 2, "0"))[::-1]
    except ValueError as exc:
        raise ElfFixupReplayError(f"`{field}` is not valid hex: {value!r}") from exc


def _hex_blob_to_bytes(value: str, *, field: str) -> bytes:
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ElfFixupReplayError(f"`{field}` is not valid hex data") from exc


def _ensure_range(output: bytearray, offset: int, width: int, *, field: str) -> None:
    if offset + width > len(output):
        raise ElfFixupReplayError(
            f"`{field}` writes past the current output size: "
            f"offset={offset}, width={width}, size={len(output)}"
        )


def _ensure_expected_before(output: bytearray, offset: int, before: bytes, *, field: str) -> None:
    current = bytes(output[offset:offset + len(before)])
    if current != before:
        raise ElfFixupReplayError(
            f"`{field}` before-check failed at offset {offset}: "
            f"expected {before.hex()}, got {current.hex()}"
        )
