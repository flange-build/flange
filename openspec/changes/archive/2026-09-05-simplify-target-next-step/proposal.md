## Why

选择系统目标后，原有“下一步”同时列出 App（应用）和系统命令，不能直接表达最常用的后续操作。
将提示统一为 `flange build 或 flange plan`，让用户立即构建系统或先查看构建计划。

## What Changes

- `flange target select` 成功后的文字提示改为“下一步  flange build 或 flange plan”。
- 在 CLI（命令行界面）体验规格与文档中记录该约定，并更新真实终端截图。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `cli-experience`：明确选择目标后引导系统构建与计划预览。

## Impact

涉及 `builder/commands.py` 的目标选择提示、CLI 体验文档和终端示例图片。
沿用现有命令着色与机器输出边界。

## 非目标

不改变目标选择、状态保存、构建、计划或 App 命令的执行行为。
