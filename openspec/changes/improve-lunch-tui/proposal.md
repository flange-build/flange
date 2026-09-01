## Why

`lunch` 无参数时把全部目标打成一张编号平表让用户输数字。当前有 **90 个目标**
（18 块板 × product × variant），一屏放不下，且这张表把已有的层级结构完全抹平：
用户其实是先想清楚"哪个平台、哪颗 SoC、哪块板"，再决定 product 与 variant，
而平表要求他在 90 行里用肉眼做这件事。

选中之后同样没有任何反馈。用户看不到这个目标究竟意味着什么配置 —— 内核走哪个
源、分区怎么切、rootfs 装什么、recovery 开没开。要确认这些只能去翻多层
`config.jsonnet` 的继承链，而那正是配置分层想替用户省掉的工作。

## What Changes

- `lunch` 无参数时进入 TUI：左侧按 平台 → SoC → 板 → product → variant 的层级
  浏览，右侧显示当前节点信息；停在末级目标上时加载并显示该目标的完整配置表。
- 配置求值约 1.3s，不能挡住方向键：配置表在后台线程加载并缓存，加载中显示
  占位，完成后自动刷新。
- 打开时自动展开并定位到当前已选目标。
- 支持按名字过滤，在 90 个目标里直接定位。
- 非 TTY 环境（管道、CI）与 `lunch --no-tui` 回退到原有编号列表，行为不变。
- `lunch <target>` 与 `--product=` / `--variant=` 的既有用法完全不变。

## Capabilities

### New Capabilities

无。TUI 是 `lunch` 这一既有能力的交互形式，不引入新的构建语义。

### Modified Capabilities

- `cli-envsetup`：补充 `lunch` 的交互式选择契约（层级浏览、配置表、回退条件）。
