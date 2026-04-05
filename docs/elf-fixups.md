# ELF `fixups.json` 说明

本文说明 `ElfTools.dumpModule(...)` 导出的 `fixups.json` 是什么、怎么读、以及字段缩写分别代表什么。

目标有两个：

- 让人类在查看 dump 结果时，能快速判断“哪一个修复阶段改了什么”
- 让 LLM 或脚本能够稳定地把 `raw` 重放成 `fixed`

## 1. 它解决的是什么问题

`dumpModule()` 默认会导出：

- `*.raw.so`
- `*.fixed.so`
- `fixups.json`
- `symbols.json`
- `proc_maps.txt`
- `manifest.json`

其中：

- `raw` 是直接从进程内存拷出来的原始镜像
- `fixed` 是为了让 IDA / 通用 ELF 工具更容易分析而修过的最终文件
- `fixups.json` 记录的是“如何从 `raw` 变成 `fixed`”

`fixups.json` 不是“再存一份完整 fixed so”，而是把修复过程收束成可读、可重放的 patch 记录。

## 2. 顶层结构

当前格式版本是 staged v2：

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

字段说明：

- `version`
  当前 schema 版本。现在是 `2`。
- `strategy`
  当前重放策略名。现在是 `raw-to-fixed-staged-v2`。
- `raw_size`
  `raw` 文件大小，单位是字节。
- `fixed_size`
  `fixed` 文件大小，单位是字节。
- `stages`
  分阶段 patch 列表。重放时必须按这里的顺序执行。

## 3. Stage 顺序

当前 stage 顺序固定为：

1. `phdr-rebase`
2. `dynamic-rebase`
3. `dynsym-fixups`
4. `relocation-fixups`
5. `section-rebuild`
6. `header-finalize`

这几个名字不是事后猜的标签，而是修复逻辑真正执行时所属的阶段。

### `phdr-rebase`

作用：

- 修正 `PT_LOAD` 对应 program header 的 `p_offset`
- 修正 `p_vaddr`
- 修正 `p_paddr`
- 修正 `p_filesz`

你看到这个阶段的 patch，基本就可以理解成“把运行时地址语义收束回分析文件语义”。

### `dynamic-rebase`

作用：

- 修正 dynamic table 里带地址语义的 `d_un`
- 同时依据 `DT_*` 内容补齐后续 section rebuild 需要的 section descriptor

### `dynsym-fixups`

作用：

- 修正 `.dynsym` 中的 `st_value`
- 在需要时修正 `st_info`

### `relocation-fixups`

作用：

- 修正 `.rel[a].dyn` / `.rel[a].plt` 里 relocation entry 的 `r_offset`
- 额外修正 `RELATIVE` 重定位目标槽位里的值

这里有两个层次：

- 第一层是把 relocation entry 自己的 `r_offset` 从运行时地址语义收束回 dumped image 里的文件内偏移
- 第二层才是对 `RELATIVE` 这类重定位，把目标槽位中已经写入的运行时值一起回调到 fixed image 语义

### `section-rebuild`

作用：

- 回填 `.shstrtab`
- 重建 section header table
- 修正 `ehdr` 中与 section table 相关的字段，例如 `e_shoff`、`e_shnum`

### `header-finalize`

作用：

- 做最小 ELF 头规范化
- 例如修正 `e_entry`、`e_type`、`e_machine`、`e_version`、`EI_OSABI`

这个阶段不会再去重建大块 section 内容，主要是让最终文件更容易被 ELF 工具识别。

## 4. Patch 类型

`patches` 里当前有三种 patch：

- `f`: field patch
- `s`: slot batch patch
- `x`: block patch

### 4.1 `f` = field patch

适用于少量、明确、值得单独阅读的字段。

示例：

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

字段说明：

- `t`
  patch 类型。这里固定是 `"f"`。
- `n`
  字段名，`name` 的缩写。
- `o`
  写入偏移，`offset` 的缩写。基于文件偏移，单位是字节。
- `w`
  字段宽度，`width` 的缩写。单位是字节。
- `b`
  修改前的值，`before` 的缩写。
- `a`
  修改后的值，`after` 的缩写。

`b` / `a` 的编码规则：

- 都是带 `0x` 的十六进制标量值
- 语义上是“这个字段的数值”
- 不是原始字节流的逐字节 hex dump

也就是说：

- `o` 决定字段写到文件哪里
- `w` 决定字段宽度
- `a` 决定写入后的最终数值

如果你要重放成字节，需要按小端把 `a` 展开回 `w` 个字节。

### 4.2 `s` = slot batch patch

适用于同一类语义、同一宽度、但会大量出现的离散字段修改。

示例：

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

字段说明：

- `t`
  patch 类型。这里固定是 `"s"`。
- `n`
  这一批 slot 的语义名。
- `w`
  每个 slot 的宽度，单位是字节。
- `v`
  `values` 的缩写，内容是一个数组。每个元素固定是：
  `[offset, before_hex, after_hex]`

也就是：

- `v[i][0]` 是偏移
- `v[i][1]` 是修改前
- `v[i][2]` 是修改后

`before_hex` / `after_hex` 与 `f.b` / `f.a` 的编码规则完全一样，都是标量值，不是原始字节串。

### 4.3 `x` = block patch

适用于连续大块写入，例如：

- `.shstrtab`
- 整个 section header table
- 或某段无法自然拆成 `f` / `s` 的连续数据

示例：

```json
{
  "t": "x",
  "n": "section_headers",
  "o": 4182016,
  "r": 0,
  "x": "000000000000..."
}
```

字段说明：

- `t`
  patch 类型。这里固定是 `"x"`。
- `n`
  这段 block 的语义名。
- `o`
  写入偏移。
- `r`
  要替换掉多少原始字节，`replace_size` 的缩写。
- `x`
  真实写入数据的十六进制字符串。

这里的 `x` 和 `f/s` 不一样：

- `x` 是原始字节流，按文件顺序直接展开
- 不带 `0x`
- 不是标量值

所以：

- `f/s` 更像“字段数值 patch”
- `x` 更像“字节块 patch”

## 5. 怎么快速看一份 `fixups.json`

推荐按下面顺序看：

1. 先看 `strategy`
   确认是不是当前支持的 staged v2。
2. 再看 `stages[*].name`
   确认阶段顺序有没有异常。
3. 再看 `section-rebuild`
   这是最容易确认“有没有真正补出 section table”的阶段。
4. 再看 `header-finalize`
   重点看 `ehdr.e_entry`、`ehdr.e_machine`、`ehdr.e_type`、`ehdr.e_version`。
5. 如果怀疑 dynsym 或 relocation 没修对，再看 `dynsym-fixups` / `relocation-fixups`。

一个经验判断：

- 如果 `raw` 的 `e_shnum` 很小，而 `fixed` 的 `e_shnum` 变成了更合理的值，同时 `section-rebuild` 阶段出现了 `shstrtab` 和 `section_headers` 两个 `x` patch，通常说明 section rebuild 已经真正生效。

## 6. 重放规则

重放时规则很简单：

1. 从 `raw` 文件开始
2. 按 `stages` 顺序执行
3. 每个 stage 内按 `patches` 顺序执行

执行规则：

- `f`
  在 `o` 位置写入 `a` 对应的 `w` 字节小端值
- `s`
  对 `v` 中每一个 slot，按它自己的 `offset` 写入 `after_hex`
- `x`
  在 `o` 位置执行 block replace
  - 替换长度是 `r`
  - 写入内容是 `x`
  - 如果 `r == 0` 且 `o` 正好等于当前文件尾，就等价于 append

最终得到的结果应该与 `fixed` 文件字节级一致。

## 7. 与 `manifest.json` 的关系

`manifest.json` 里会保留一份摘要：

- `fix.strategy`
- `fix.stages`
- `fix.header_before`
- `fix.header_after`
- `fix.change_record.stage_count`
- `fix.change_record.patch_count`

理解方式：

- `fixups.json` 是完整 patch 记录
- `manifest.json` 是适合快速总览的摘要

如果只想快速判断这次修了什么，看 `manifest.json` 就够。
如果要精确分析每个字段或重放结果，看 `fixups.json`。

## 8. 当前字段缩写速查

### 顶层

- `raw_size`: `raw` 文件大小
- `fixed_size`: `fixed` 文件大小

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

## 9. 对 LLM 的建议

如果让 LLM 帮你分析一份 `fixups.json`，建议明确告诉它：

- 这是 staged v2 schema
- `f/s` 里的 hex 是字段数值，不是文件顺序原始字节
- `x` 里的 hex 才是原始字节块
- stage 顺序固定，不要自行重排

同时最好把下面几份文件一起给它：

- `fixups.json`
- `manifest.json`
- `raw`
- `fixed`

这样它既能解释“为什么改”，也能校验“改完是不是一致”。
