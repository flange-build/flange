## Why

当前完整 pytest 存在 42 个失败，其中大部分测试仍按旧目录、旧私有接口或旧配置默认值断言，另有 2 个网络测试仅因受限沙箱禁止回环 socket 而失败；同时 3 个已实现的历史 change 和 1 条主规格无法通过 OpenSpec strict 校验。需要在本次板级功能收尾时清理这些质量债务，恢复可信、可重复的全量质量门禁。

## What Changes

- 将旧测试同步到当前公开接口、三层仓库路径、动态必需产物和配置默认值，不删除仍能表达有效行为的测试。
- 将依赖本机回环 socket 的测试明确归类为需要普通宿主权限的用例，并在允许该能力的环境中验证。
- 修正 OpenSpec 主规格的规范措辞，审计并归档已经落地但缺少 delta 的历史 change。
- 以完整 pytest 零失败和 `openspec validate --all --strict` 零失败作为收尾门禁，并把结果同步到归档验收证据与 wiki。
- 不改变构建、刷写、缓存或板级运行时行为；若测试暴露真实缺陷，仅做满足既有规格的最小修复。

## 非目标

- 不通过批量删除、跳过或放宽断言来掩盖可修复的失败。
- 不重构 `resolve_conditions` 递归注入 `product` / `variant` 等既有契约。
- 不修改或提交并行开发中的 YT8512C 补丁及其 OpenSpec change。
- 不把宿主机虚拟环境或 `.build/` 派生产物提交到仓库。

## Capabilities

### New Capabilities

- `repository-quality-gate`: 定义 pytest 与 OpenSpec strict 的仓库级收尾门禁、受限环境用例判定和测试契约同步要求。

### Modified Capabilities

- `adbd-app`: 将旧 `app/`、Bazel 和 `board.bzl` 契约同步为当前 `components/app/`、Python AppBuilder 与 `config.py` 架构。

## Impact

- 测试：`tests/builder/`、`tests/config/` 中与现有接口漂移的用例。
- 规格：`openspec/specs/rootfs-user-system/spec.md`、历史 change 的归档状态，以及新增质量门禁规格。
- 文档：ATK-RK3506B 已归档变更的验收证据与对应 wiki 状态。
- 兼容性：无运行时 API 或产物格式变更；保留全部 42 个既有测试覆盖。
