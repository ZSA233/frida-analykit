from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from frida_analykit.scripts.elf_fixups import (
    ElfFixupReplayError,
    FIXUP_STAGE_ORDER,
    replay_elf_fixups,
)


def _fixed_elf_header() -> bytes:
    data = bytearray(64)
    data[0:4] = b"\x7fELF"
    data[4] = 2
    data[5] = 1
    data[6] = 1
    data[7] = 0
    data[16:18] = (3).to_bytes(2, "little")
    data[18:20] = (183).to_bytes(2, "little")
    data[20:24] = (1).to_bytes(4, "little")
    return bytes(data)


def _fixups_payload(raw: bytes, fixed: bytes) -> dict[str, object]:
    return {
        "version": 2,
        "strategy": "raw-to-fixed-staged-v2",
        "raw_size": len(raw),
        "fixed_size": len(fixed),
        "stages": [
            {"name": "phdr-rebase", "detail": "synthetic phdr stage", "patches": []},
            {"name": "dynamic-rebase", "detail": "synthetic dynamic stage", "patches": []},
            {"name": "dynsym-fixups", "detail": "synthetic dynsym stage", "patches": []},
            {"name": "relocation-fixups", "detail": "synthetic relocation stage", "patches": []},
            {
                "name": "section-rebuild",
                "detail": "synthetic section stage",
                "patches": [
                    {
                        "t": "x",
                        "n": "synthetic-fixed-image",
                        "o": 0,
                        "r": len(raw),
                        "x": fixed.hex(),
                    }
                ],
            },
            {"name": "header-finalize", "detail": "synthetic header stage", "patches": []},
        ],
    }


def test_replay_elf_fixups_reconstructs_fixed_bytes() -> None:
    raw = b"abcde"
    fixed = _fixed_elf_header()
    fixups = _fixups_payload(raw, fixed)

    assert replay_elf_fixups(raw, fixups) == fixed
    assert [stage["name"] for stage in fixups["stages"]] == list(FIXUP_STAGE_ORDER)


def test_replay_elf_fixups_detects_before_mismatch_when_requested() -> None:
    raw = b"\x34\x12"
    fixups = {
        "version": 2,
        "strategy": "raw-to-fixed-staged-v2",
        "raw_size": 2,
        "fixed_size": 2,
        "stages": [
            {"name": "phdr-rebase", "detail": "", "patches": []},
            {"name": "dynamic-rebase", "detail": "", "patches": []},
            {"name": "dynsym-fixups", "detail": "", "patches": []},
            {"name": "relocation-fixups", "detail": "", "patches": []},
            {"name": "section-rebuild", "detail": "", "patches": []},
            {
                "name": "header-finalize",
                "detail": "",
                "patches": [
                    {"t": "f", "n": "ehdr.e_type", "o": 0, "w": 2, "b": "0x9999", "a": "0x1234"}
                ],
            },
        ],
    }

    with pytest.raises(ElfFixupReplayError, match="before-check failed"):
        replay_elf_fixups(raw, fixups, check_before=True)


def test_replay_elf_fixups_script_replays_dump_dir(tmp_path: Path) -> None:
    dump_dir = tmp_path / "dump"
    dump_dir.mkdir()

    raw = b"abcde"
    fixed = _fixed_elf_header()
    fixups = _fixups_payload(raw, fixed)

    raw_path = dump_dir / "libc.raw.so"
    fixed_path = dump_dir / "libc.fixed.so"
    fixups_path = dump_dir / "fixups.json"

    raw_path.write_bytes(raw)
    fixed_path.write_bytes(fixed)
    fixups_path.write_text(json.dumps(fixups), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/replay_elf_fixups.py", str(dump_dir), "--json"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    output_path = Path(payload["output_path"])
    assert output_path.read_bytes() == fixed
    assert payload["compare_path"] == str(fixed_path)
    assert payload["compare_matched"] is True
    assert payload["stage_count"] == len(FIXUP_STAGE_ORDER)
    assert payload["patch_count"] == 1
