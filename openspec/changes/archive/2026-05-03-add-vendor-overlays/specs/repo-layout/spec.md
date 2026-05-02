## MODIFIED Requirements

### Requirement: 内容层职责边界

`components/` 层 MUST 仅包含仓库携带的"原料型"内容：应用源码、软件包定义、rootfs 基线配置与 overlay、板型定义、平台数据（patches、配置清单、SoC 级子目录），以及外部 vendor 资源（包括但不限于 device tree overlay 仓库的 source pin）。`components/` 下的目录 MUST 可被版本控制跟踪，MUST NOT 包含构建生成的派生物。

#### Scenario: 组件源码归属

- **WHEN** 仓库携带应用 / 软件包 / rootfs 基线配置或 overlay / 板型定义 / 平台数据
- **THEN** 这些内容 MUST 分别位于 `components/app/`、`components/packages/`、`components/rootfs/`、`components/board/`、`components/platform/` 下

#### Scenario: rootfs 基线配置归属

- **WHEN** 需要声明平台无关的 rootfs apt 包集合或 overlay
- **THEN** 这些内容 MUST 位于 `components/rootfs/` 下，并在配置解析阶段合并到最终 `rootfs.packages`

#### Scenario: 平台数据与平台逻辑分离

- **WHEN** 需要为某个 SoC 家族维护 patches、配置清单与 SoC 子目录
- **THEN** 这些内容 MUST 位于 `components/platform/<soc>/`，与 `builder/platforms/<soc>/` 中的构建逻辑按"数据与代码分离"的原则分别维护

#### Scenario: 外部 vendor overlay 仓库 source 归属

- **WHEN** 仓库需要消费外部 vendor 维护的 device tree overlay 仓库（例如 radxa-overlays）
- **THEN** 该 source pin（git URL + ref）与默认配置 MUST 位于 `components/device-tree-overlay/` 下，构建逻辑位于 `builder/overlays.py`，遵循"数据与代码分离"原则

#### Scenario: 内容层不得存放运行时产物

- **WHEN** 构建过程生成中间文件或最终镜像
- **THEN** 该产物 MUST NOT 写入 `components/` 层；MUST 写入 `.build/` 层
