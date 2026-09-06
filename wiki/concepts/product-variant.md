---
title: product-variant
type: concept
status: stable
sources:
  - builder/workspace.py
  - builder/config/query.py
  - components/board/radxa-zero3w/config.jsonnet
  - docs/development-guide.md
updated: 2026-09-05
---

# board、product 与 variant

Target（构建目标）是 `board + product + variant`：board 指硬件，product 指软件用途，
variant 指调试/发布差异。例如 `radxa-zero3w-desktop-debug` 选择 Zero 3W 的桌面调试系统。
每块板支持的维度来自其配置，不能假定所有板都提供同一 product。

```bash
flange target list radxa-zero3w
flange target select radxa-zero3w-default-debug
flange target show
flange --target radxa-zero3w-desktop-release plan image
```

`lunch <完整目标>` 是 `flange target select <完整目标>` 的薄包装。
当前选择保存到 `<workspace_root>/.flange/current_config`，只记录三个目标字段；后续命令重新求值配置。
优先级为本次 `--target` → 当前工作区保存选择 → `flange.toml` 的 `[target]` 默认值。

board 与 product 都可以包含连字符。所有入口使用
[`builder/config/query.py`](../../builder/config/query.py) 的统一解析器，不应自己按 `-` 简单拆分。
切换目标时选择完整名称，旧 `lunch --variant=...` 用法已不适用。

每个目标有独立的 `<build_root>/work/<target.key>/` 和
`<build_root>/target/<board>/<product>/<variant>/`。同一工作区的终端共享保存选择；
同时操作不同目标时，显式 `--target` 能避免互相切换。

product/variant 条件在 Jsonnet 中求值，详见[配置组合](三层继承.md)与
[最终配置](FINAL_CONFIG.md)；完整非交互用法见[开发指南](../../docs/development-guide.md)。
