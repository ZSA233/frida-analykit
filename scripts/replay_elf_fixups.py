#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from frida_analykit.scripts.elf_fixups import ElfFixupReplayError, ElfFixupReplaySummary, replay_elf_fixups_to_path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay staged ELF fixups.json into a reconstructed fixed ELF. "
            "INPUT may be either a dump directory or a *.raw.so file."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Dump directory or raw ELF path",
    )
    parser.add_argument(
        "--fixups",
        type=Path,
        default=None,
        help="Explicit fixups.json path when INPUT is a raw ELF file",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output ELF path; defaults to a sibling *.replayed.so",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="Optional fixed ELF to compare against after replay",
    )
    parser.add_argument(
        "--check-before",
        action="store_true",
        help="Verify staged before-values for field/slot patches before overwriting them",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the replay summary as JSON",
    )
    return parser.parse_args(argv)


def _resolve_inputs(
    input_path: Path,
    *,
    fixups_path: Path | None,
    output_path: Path | None,
    compare_path: Path | None,
) -> tuple[Path, Path, Path, Path | None]:
    resolved_input = input_path.expanduser().resolve()
    if resolved_input.is_dir():
        if fixups_path is not None:
            raise ElfFixupReplayError("`--fixups` is not needed when INPUT is a dump directory")
        raw_candidates = sorted(path for path in resolved_input.iterdir() if path.is_file() and path.name.endswith(".raw.so"))
        if not raw_candidates:
            raise ElfFixupReplayError(f"no `*.raw.so` file was found under `{resolved_input}`")
        if len(raw_candidates) > 1:
            names = ", ".join(path.name for path in raw_candidates)
            raise ElfFixupReplayError(
                f"expected exactly one `*.raw.so` file under `{resolved_input}`, found: {names}"
            )
        raw_path = raw_candidates[0]
        selected_fixups = resolved_input / "fixups.json"
        if not selected_fixups.is_file():
            raise ElfFixupReplayError(f"`{resolved_input}` does not contain `fixups.json`")
        selected_compare = compare_path
        if selected_compare is None:
            sibling_fixed = raw_path.with_name(raw_path.name.removesuffix(".raw.so") + ".fixed.so")
            if sibling_fixed.is_file():
                selected_compare = sibling_fixed
        selected_output = output_path or _default_output_path(raw_path)
        return raw_path, selected_fixups, selected_output, selected_compare

    if not resolved_input.is_file():
        raise ElfFixupReplayError(f"input path `{resolved_input}` does not exist")

    raw_path = resolved_input
    selected_fixups = fixups_path.expanduser().resolve() if fixups_path is not None else raw_path.with_name("fixups.json")
    if not selected_fixups.is_file():
        raise ElfFixupReplayError(
            f"fixups file `{selected_fixups}` does not exist; pass `--fixups` explicitly"
        )
    selected_output = output_path or _default_output_path(raw_path)
    selected_compare = compare_path.expanduser().resolve() if compare_path is not None else None
    if selected_compare is None and raw_path.name.endswith(".raw.so"):
        sibling_fixed = raw_path.with_name(raw_path.name.removesuffix(".raw.so") + ".fixed.so")
        if sibling_fixed.is_file():
            selected_compare = sibling_fixed
    return raw_path, selected_fixups, selected_output, selected_compare


def _default_output_path(raw_path: Path) -> Path:
    name = raw_path.name
    if name.endswith(".raw.so"):
        return raw_path.with_name(name.removesuffix(".raw.so") + ".replayed.so")
    if name.endswith(".so"):
        return raw_path.with_name(name.removesuffix(".so") + ".replayed.so")
    return raw_path.with_name(name + ".replayed")


def _render_summary_json(summary: ElfFixupReplaySummary) -> str:
    payload = {
        "raw_path": str(summary.raw_path),
        "fixups_path": str(summary.fixups_path),
        "output_path": str(summary.output_path),
        "raw_size": summary.raw_size,
        "fixed_size": summary.fixed_size,
        "stage_count": summary.stage_count,
        "patch_count": summary.patch_count,
        "compare_path": str(summary.compare_path) if summary.compare_path is not None else None,
        "compare_matched": summary.compare_matched,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        raw_path, fixups_path, output_path, compare_path = _resolve_inputs(
            args.input,
            fixups_path=args.fixups,
            output_path=args.out.expanduser().resolve() if args.out is not None else None,
            compare_path=args.compare,
        )
        summary = replay_elf_fixups_to_path(
            raw_path=raw_path,
            fixups_path=fixups_path,
            output_path=output_path,
            compare_path=compare_path,
            check_before=args.check_before,
        )
    except ElfFixupReplayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(_render_summary_json(summary))
        return 0

    print(
        f"replayed `{summary.raw_path}` -> `{summary.output_path}` "
        f"using `{summary.fixups_path}` ({summary.raw_size} -> {summary.fixed_size} bytes)"
    )
    print(
        f"stages={summary.stage_count} patches={summary.patch_count}"
    )
    if summary.compare_path is not None:
        print(f"compare `{summary.compare_path}`: matched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
