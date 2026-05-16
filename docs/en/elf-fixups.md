# ELF `fixups.json` Guide

This document explains what the `fixups.json` exported by `ElfTools.dumpModule(...)` means, how to read it, and what each abbreviated field represents.

It has two goals:

- help humans quickly understand which fixup stage changed which data
- let LLMs or scripts reliably replay `raw` into `fixed`

If you only want to replay `raw + fixups.json` from a dump directory into a comparable ELF, use the repository script:

```sh
python scripts/replay_elf_fixups.py /path/to/dump-dir --json
```

You can also specify the files explicitly:

```sh
python scripts/replay_elf_fixups.py /path/to/libfoo.raw.so \
  --fixups /path/to/fixups.json \
  --out /path/to/libfoo.replayed.so \
  --compare /path/to/libfoo.fixed.so \
  --check-before
```

Script behavior:

- When given a dump directory, it finds the unique `*.raw.so` and `fixups.json` in that directory.
- If a same-basename `*.fixed.so` exists in the directory, the script compares against it automatically.
- The default output name is `*.replayed.so`.
- `--check-before` validates the `b` fields in `f/s` patches so mismatched fixups are detected earlier.

## 1. What It Solves

`dumpModule()` exports these files by default:

- `*.raw.so`
- `*.fixed.so`
- `fixups.json`
- `symbols.json`
- `proc_maps.txt`
- `manifest.json`

Meaning:

- `raw` is the original image copied directly from process memory.
- `fixed` is the final file adjusted for IDA and common ELF tools.
- `fixups.json` records how to transform `raw` into `fixed`.

`fixups.json` is not another copy of the full fixed shared object. It is a readable and replayable patch record of the repair process.

## 2. Top-Level Structure

The current format version is staged v2:

```json
{
  "version": 2,
  "strategy": "raw-to-fixed-staged-v2",
  "raw_size": 4182016,
  "fixed_size": 4183182,
  "stages": [
    {
      "name": "phdr-rebase",
      "detail": "...",
      "patches": []
    }
  ]
}
```

Field meanings:

- `version`
  Current schema version. It is `2`.
- `strategy`
  Current replay strategy name. It is `raw-to-fixed-staged-v2`.
- `raw_size`
  Size of the `raw` file in bytes.
- `fixed_size`
  Size of the `fixed` file in bytes.
- `stages`
  Ordered patch stages. Replay must execute them in this order.

## 3. Stage Order

The current stage order is fixed:

1. `phdr-rebase`
2. `dynamic-rebase`
3. `dynsym-fixups`
4. `relocation-fixups`
5. `section-rebuild`
6. `header-finalize`

These names are not guessed labels added after the fact. They correspond to the real repair stage that produced each patch.

### `phdr-rebase`

Purpose:

- fixes `p_offset` for `PT_LOAD` program headers
- fixes `p_vaddr`
- fixes `p_paddr`
- fixes `p_filesz`

Patches in this stage usually mean runtime address semantics are being converted back into file-analysis semantics.

### `dynamic-rebase`

Purpose:

- fixes address-like `d_un` fields in the dynamic table
- fills section descriptors needed by later section rebuild logic based on `DT_*` entries

### `dynsym-fixups`

Purpose:

- conservatively fixes `.dynsym` with coverage similar to `fix.cpp`
- infers `st_info` only for `STT_NOTYPE` entries clearly inside the dumped image
- rebases `st_value` only for entries that clearly have address semantics

The design is not "change every high type to `FUNC/OBJECT`" and not "subtract load bias from every positive `st_value`".

The current logic intentionally preserves:

- `TLS`
- `IFUNC`
- `COMMON`
- `FILE`
- OS / processor specific symbol types
- `SHN_UNDEF` / `SHN_ABS` or values clearly outside the dumped image

### `relocation-fixups`

Purpose:

- fixes `r_offset` in `.rel[a].dyn` / `.rel[a].plt` relocation entries
- additionally fixes target-slot values for `RELATIVE` relocations

There are two layers:

- The first layer converts the relocation entry's own `r_offset` from runtime address semantics back to an offset inside the dumped file.
- The second layer adjusts the target slot value already written by a `RELATIVE` relocation back to fixed-image semantics.

### `section-rebuild`

Purpose:

- writes `.shstrtab`
- rebuilds the section header table
- fixes section-table-related ELF header fields such as `e_shoff` and `e_shnum`

### `header-finalize`

Purpose:

- performs minimal ELF header normalization
- for example fixes `e_entry`, `e_type`, `e_machine`, `e_version`, and `EI_OSABI`

This stage does not rebuild large section contents. It mainly makes the final file easier for ELF tools to recognize.

## 4. Patch Types

`patches` currently contains three patch types:

- `f`: field patch
- `s`: slot batch patch
- `x`: block patch

### 4.1 `f` = field patch

Use this for small, explicit fields that are worth reading individually.

Example:

```json
{
  "t": "f",
  "n": "ehdr.e_machine",
  "o": 18,
  "w": 2,
  "b": "0xd61f",
  "a": "0x00b7"
}
```

Field meanings:

- `t`
  Patch type. It is always `"f"` here.
- `n`
  Field name.
- `o`
  Write offset, in bytes, based on file offset.
- `w`
  Field width in bytes.
- `b`
  Value before modification.
- `a`
  Value after modification.

Encoding rules for `b` / `a`:

- both are scalar hex values with a `0x` prefix
- semantically they are the numeric value of the field
- they are not raw byte-order hex dumps

So:

- `o` decides where the field is written
- `w` decides the field width
- `a` decides the final numeric value

When replaying into bytes, expand `a` into `w` little-endian bytes.

### 4.2 `s` = slot batch patch

Use this for many discrete field changes with the same semantics and width.

Example:

```json
{
  "t": "s",
  "n": "dynsym.st_value",
  "w": 8,
  "v": [
    [4096, "0x7108c12340", "0x00000012340"],
    [4120, "0x7108c23450", "0x00000023450"]
  ]
}
```

Field meanings:

- `t`
  Patch type. It is always `"s"` here.
- `n`
  Semantic name for this batch of slots.
- `w`
  Width of each slot in bytes.
- `v`
  Values array. Each entry is fixed as:
  `[offset, before_hex, after_hex]`

That means:

- `v[i][0]` is the offset
- `v[i][1]` is the value before modification
- `v[i][2]` is the value after modification

`before_hex` / `after_hex` follow the same encoding rules as `f.b` / `f.a`: scalar values, not raw byte strings.

### 4.3 `x` = block patch

Use this for continuous block writes, for example:

- `.shstrtab`
- the full section header table
- continuous data that does not naturally fit `f` / `s`

Example:

```json
{
  "t": "x",
  "n": "section_headers",
  "o": 4182016,
  "r": 0,
  "x": "000000000000..."
}
```

Field meanings:

- `t`
  Patch type. It is always `"x"` here.
- `n`
  Semantic name for the block.
- `o`
  Write offset.
- `r`
  Number of original bytes to replace.
- `x`
  Hex string for the actual bytes to write.

Here `x` differs from `f/s`:

- `x` is raw byte-stream hex in file order
- it has no `0x` prefix
- it is not a scalar value

So:

- `f/s` are field-value patches
- `x` is a byte-block patch

## 5. How To Read A `fixups.json` Quickly

Recommended order:

1. Check `strategy`
   Confirm it is the supported staged v2 strategy.
2. Check `stages[*].name`
   Confirm the stage order is not unusual.
3. Check `section-rebuild`
   This is the easiest place to confirm whether a section table was rebuilt.
4. Check `header-finalize`
   Focus on `ehdr.e_entry`, `ehdr.e_machine`, `ehdr.e_type`, and `ehdr.e_version`.
5. If dynsym or relocation looks suspicious, inspect `dynsym-fixups` / `relocation-fixups`.

Rule of thumb:

- If `raw` has a very small `e_shnum`, while `fixed` has a more reasonable `e_shnum`, and the `section-rebuild` stage contains both `shstrtab` and `section_headers` `x` patches, section rebuild likely worked.

## 6. Replay Rules

Replay is straightforward:

1. Start from the `raw` file.
2. Execute stages in `stages` order.
3. Execute patches in each stage in `patches` order.

Execution rules:

- `f`
  Write the `w` little-endian bytes represented by `a` at `o`.
- `s`
  For each slot in `v`, write `after_hex` at that slot's offset.
- `x`
  Perform a block replace at `o`.
  - Replacement length is `r`.
  - Written content is `x`.
  - If `r == 0` and `o` is exactly the current end of file, it is an append.

The final result should be byte-identical to the `fixed` file.

## 7. Relationship With `manifest.json`

`manifest.json` keeps a summary:

- `fix.strategy`
- `fix.stages`
- `fix.header_before`
- `fix.header_after`
- `fix.change_record.stage_count`
- `fix.change_record.patch_count`

Interpretation:

- `fixups.json` is the complete patch record.
- `manifest.json` is a quick overview.

Use `manifest.json` when you only need a quick summary of what changed.
Use `fixups.json` when you need exact field-level analysis or replay.

## 8. Current Field Abbreviation Reference

### Top Level

- `raw_size`: size of the `raw` file
- `fixed_size`: size of the `fixed` file

### `f`

- `t`: type
- `n`: name
- `o`: offset
- `w`: width
- `b`: before
- `a`: after

### `s`

- `t`: type
- `n`: name
- `w`: width
- `v`: values

### `x`

- `t`: type
- `n`: name
- `o`: offset
- `r`: replace size
- `x`: hex bytes

## 9. Advice For LLMs

When asking an LLM to analyze a `fixups.json`, tell it explicitly:

- this is the staged v2 schema
- hex in `f/s` is a field value, not file-order raw bytes
- hex in `x` is the raw byte block
- stage order is fixed and must not be rearranged

Ideally provide these files together:

- `fixups.json`
- `manifest.json`
- `raw`
- `fixed`

That lets it explain why changes were made and also verify that the replay result matches.

