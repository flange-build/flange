## Context

Ubuntu 的普通 UID/GID 范围从 1000 开始，桌面安装创建的首个交互用户通常取得 UID 1000，并拥有同名、GID 1000 的 user private group（用户私有组）。当前 flange 先以普通组方式预创 `rootfs.groups`，因此缺失的 `i2c`、`spi`、`gpio` 依次占用 GID 1000～1002，随后 `useradd -U flange` 只能创建 GID 1003；同时命令没有固定 UID，前置软件若误建普通用户还可能占用 UID 1000。

账号逻辑已统一收敛在 `RootfsBuilder._configure_users()`，所有平台均经过该入口。构建缓存的 logic 指纹包含 `builder/rootfs.py`，修改共享实现会使 rootfs 产物失效重建。

## Goals / Non-Goals

**Goals:**

- `default_user` 非空时始终得到 UID 1000 与同名 GID 1000 用户私有组。
- 新建的顶层附加组使用 Ubuntu system group（系统组）编号范围，不消耗 GID 1000 以上的普通用户编号。
- 编号冲突在构建阶段明确失败，避免产出身份静默漂移的镜像。
- 保持现有配置结构和跨平台共享实现。

**Non-Goals:**

- 不实现 fnOS 的 `Administrators` / `Users` 组模型。
- 不增加可配置 UID/GID 字段。
- 不迁移已部署系统中的账号与文件所有权。

## Decisions

### 1. 默认用户显式保留 1000:1000

在创建普通用户前，对 `default_user` 执行 `groupadd -g 1000 <name>`；创建该用户时执行 `useradd -u 1000 -g <name>`，不使用 `-U`。遍历多个用户时先创建 `default_user`，其余用户继续使用原有 `useradd -U` 自动分配。

选择显式编号而不是仅依赖“当前恰好没有普通账号”，因为 Phase 2 之前会安装 APT、App 与额外 deb；显式命令既保证已有 `/run/user/1000` 消费方的契约，也让 UID/GID 冲突通过命令失败直接暴露。固定值是 Ubuntu Desktop 首个用户规则，不扩展成新配置项。

### 2. 顶层附加组使用 system group

将预创建命令从 `groupadd -f` 改为 `groupadd -r -f`。`-r` 只影响缺失组的分配范围；`-f` 继续保证 `sudo`、`video` 等已存在组的幂等处理，不改写其既有 GID。

不采用硬编码 `i2c`、`spi`、`gpio` 数值 GID：Ubuntu 只要求它们处于系统范围，业务也通过组名授权，固定每个系统组编号没有收益。

### 3. 以命令级测试锁住构建契约

复用现有四平台 rootfs golden 测试，令同一份测试配置覆盖 system group 参数、默认用户私有组与显式 UID/GID；再用一个聚焦测试覆盖“默认用户位于字典后部”时的创建顺序。无需新增测试框架或镜像解析器。

## Risks / Trade-offs

- [基础镜像或前置包已占用 UID/GID 1000] → `groupadd` 或 `useradd` 立即失败；这是刻意的 fail-fast（快速失败），应修正污染普通编号段的前置包，而不是另选编号。
- [board 声明多个普通用户且把 `default_user` 放在字典后部] → 构建器仅调整创建顺序，确保默认用户先取得保留身份；非默认用户之间仍保持声明顺序。
- [历史镜像仍为 `1000:1003`] → 不做在线迁移；重新构建和刷写后采用新契约，存量设备由使用方另行迁移。

## Migration Plan

1. 修改共享 RootfsBuilder、规格和现行配置说明。
2. 更新并运行四平台 rootfs golden 测试及 OpenSpec 校验。
3. 下一次构建因 builder logic 指纹变化而重建 rootfs；验证新镜像的默认用户为 `1000:1000`。
4. 如需回滚，回退共享实现与文档后重新构建镜像；不提供设备内原地回滚脚本。

## Open Questions

无。
