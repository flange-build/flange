## Context

完整测试当前为 `42 failed, 1404 passed, 39 skipped`。逐项复现表明没有 42 个独立功能缺陷：40 个失败来自历史测试没有随公开接口、三层目录、必需产物检查和默认配置演进而更新；另 2 个 `recoveryctl` 用例在受限沙箱中绑定回环 socket 返回 `EPERM`，同一用例在普通宿主权限下为 `2 passed`。OpenSpec strict 另有 3 个旧 change 无 delta 和 1 条主规格缺少规范关键字。

本变更跨越 builder/config 测试、缓存测试、OpenSpec 归档和验收文档，但不引入新的运行时架构。并行开发中的 YT8512C 文件必须保持隔离。

## Goals / Non-Goals

**Goals:**

- 保留并修复全部有效测试，使完整 pytest 在具备普通本机 socket 权限的受支持 Python 环境中零失败。
- 让测试通过公开接口验证当前契约，不再依赖已删除的私有 helper 或旧顶层目录。
- 让缓存命中测试同时建立哈希文件和组件必需产物，真实覆盖当前缓存语义。
- 清理 OpenSpec strict 债务，归档已经实现的历史 change，并补齐最终验收证据。

**Non-Goals:**

- 不删除、`skip` 或弱化能在正常环境运行的测试。
- 不改变构建器、配置合并、缓存和刷写的既有运行时契约。
- 不把受限沙箱的 socket 禁令转化为生产代码兼容逻辑。
- 不触碰 YT8512C 并行变更。

## Decisions

### 1. 以现有公开契约为基准同步测试

App 编译测试断言解析后的 `-j<N>`；缓存测试统一调用 `compute_hash()` / `compute_phase_hash()`，源码变更后创建新的 `BuildCache` 实例以避开单次构建内有意保留的 memoization（记忆化）；rootfs 集成测试使用 `.build/target` 并 mock `ChrootContext` 公共边界。

备选方案是恢复 `_hash_app_sources()` 等私有方法或退回旧路径。该方案会重新引入重复接口并违反 `ProjectSpec.md` 的三层路径约定，因此不采用。

### 2. 缓存测试必须创建真实必需产物

`store()` 只记录内容哈希，`is_up_to_date()` 还会检查 kernel/rootfs 等组件产物是否存在。测试 helper 将按组件建立最小合法产物，再断言 cache hit；缺失产物的既有测试继续覆盖 cache miss。

备选方案是 mock `_required_artifacts_present()`。这会绕过本次最需要保护的行为，不采用。

### 3. 配置测试接受已发布的默认值与递归元数据

GUD 已成为相关平台的 kernel defconfig 默认项；Qualcomm 平台已进入发现集合；root 默认账号策略已切换为锁定 root；`resolve_conditions()` 会在每层 dict 注入 `product` / `variant`，且现有构建代码和主规格已显式消费该行为。测试更新为准确断言这些契约。

备选方案是借测试失败重构递归元数据。该行为影响范围远超本次质量收尾，且可能改变缓存和用户配置解析，不采用。

### 4. 环境能力失败与产品失败分开判定

完整门禁在允许绑定 `127.0.0.1` 临时端口的宿主环境执行。受限沙箱若返回 `EPERM`，必须在普通宿主权限下单独复跑相关用例；只有复跑仍失败才算产品回归。

### 5. 历史 OpenSpec change 先审计再归档

`build-optimization`、`flash-enhancement`、`python-app-packaging` 属于旧版工作流遗留：实现和测试已经进入仓库，但 change 没有 delta。将核对当前实现及主规格覆盖，补充必要 delta 或在确认属于已落地基础设施时使用 `--skip-specs` 归档；不得仅为通过校验删除 change。主规格中缺少 `SHALL/MUST` 的条目只做规范措辞修正，不改变语义。

审计若发现集成测试仍因旧仓库路径而被跳过，必须先迁移到三层路径并实际执行。对应主规格仍描述已移除机制时，通过本 change 的 MODIFIED delta 同步当前权威契约。

## Risks / Trade-offs

- [测试与当前错误行为同步] → 每一组断言都以实现历史、主规格和已有新测试交叉确认，不以“让测试绿”为唯一依据。
- [宿主 Python 版本低于项目最低 3.12] → 优先在 Python 3.12/Docker 环境复验；若本机只能提供 3.11，明确记录解释器版本并避免把环境修复提交进仓库。
- [历史 change 实现并不完整] → 未确认的任务不标完成、不归档；转成明确剩余任务，而不是伪造验收。
- [误提交并行开发文件] → 全程使用显式路径暂存并在提交前检查 staged diff。

## Migration Plan

1. 按失败分组更新测试并逐组运行。
2. 运行完整 pytest；对 socket 用例在普通宿主权限下复验。
3. 修正主规格措辞，审计并处理 3 个历史 change。
4. 运行 `openspec validate --all --strict`。
5. 更新 ATK-RK3506B 归档任务、验收证据和 wiki，最后按单一目的拆分提交。

回滚时可独立撤销测试同步或规格归档提交；本变更不迁移设备数据和构建产物。

## Open Questions

无。若审计发现历史 change 尚有未实现项，则保留为 active 并补齐合法 delta，而不是强制归档。

## 实施审计结果

- `build-optimization`：目录/App/rootfs 哈希、phase cache、builder 注入和 rootfs base snapshot 均存在；缓存、rootfs cache 与 engine 定向测试 `71 passed`。早期“直接 hash App deb”实现已由更完整的 App→rootfs Merkle 依赖取代。
- `flash-enhancement`：Python 数据模型、策略、生成器、执行器与 CLI 均存在，旧 shell 脚本已删除；定向测试 `35 passed`。
- `python-app-packaging`：AppSpec、DebBuilder、AppBuilder、五种构建系统、外部来源、sysroot、脚手架和 CLI 均存在；定向测试 `350 passed, 12 skipped`。进一步审计确认 12 个 skip 来自测试旧路径，迁移后连同真实 adbd 端到端测试为 `134 passed`，独立 `test_e2e.py` 为 `38 passed`。

## 验证记录

- 宿主定向回归：原失败涉及集合 `487 passed`；普通宿主权限下 recovery socket 用例 `2 passed`。
- 受支持环境全量回归：已有 `flange-build:latest`（Ubuntu 24.04、Python 3.12.3）一次性容器，只读挂载仓库并使用 pytest 9.1.1，结果 `1485 passed in 64.99s`，零 failed、零 skipped。
- OpenSpec 全库严格校验：`openspec validate --all --strict` 结果 `64 passed, 0 failed`。
