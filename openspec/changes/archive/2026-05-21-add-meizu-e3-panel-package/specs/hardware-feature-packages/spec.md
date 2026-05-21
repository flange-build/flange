## ADDED Requirements

### Requirement: 包清单契约

每个硬件特性包 MUST 位于 `components/packages/<pkg>/` 目录，并 MUST 提供一个 `package.py`，导出名为 `PACKAGE` 的 dict。`PACKAGE` MUST 包含 `name`（kebab-case 字符串，MUST 与目录名一致）与 `components`（列表）。`components` 中每一项 MUST 是 dict 且 MUST 含 `type` 字段，`type` 的取值 MUST 属于 `oot-driver` / `devicetree` / `deb` 之一；未知 `type` MUST 使构建失败并在错误信息中给出该 `type` 与候选集合。

#### Scenario: 合法包清单被加载

- **WHEN** `components/packages/foo/package.py` 导出 `PACKAGE = {"name": "foo", "components": [{"type": "oot-driver", "name": "bar", "dir": "driver/bar", "ko_pattern": ["bar.ko"]}]}`
- **THEN** 构建系统成功加载该包并识别出 1 个 `oot-driver` 类型 component

#### Scenario: 未知 component 类型

- **WHEN** 某 component 的 `type` 为 `firmware`（不在合法集合内）
- **THEN** 构建失败
- **AND** 错误信息包含非法值 `firmware` 与候选集合 `oot-driver` / `devicetree` / `deb`

#### Scenario: name 与目录名不一致

- **WHEN** `components/packages/foo/package.py` 的 `PACKAGE["name"]` 为 `bar`
- **THEN** 构建失败
- **AND** 错误信息指出 `name` 与目录名不一致

### Requirement: board opt-in 启用包

board 配置 MUST 通过 `packages` 字段 opt-in 启用包。`packages` 的每一项 MAY 是字符串（包名，取该包对此 board 的默认启用集），或 MAY 是 dict（含 `name` 及可选的按类型启用子集，如 `drivers`）。未声明 `packages` 或为空时，board 的构建行为 MUST 与不启用任何包保持一致（向后兼容）。引用不存在的包 MUST 使构建失败并给出包名。

#### Scenario: 字符串形式启用整包

- **WHEN** board 配置 `packages: ["meizu-e3-panel"]`
- **THEN** 构建系统加载 `meizu-e3-panel` 包并启用其对此 board 声明的默认 component 集

#### Scenario: dict 形式按需选驱动

- **WHEN** board 配置 `packages: [{"name": "meizu-e3-panel", "drivers": ["sec_ts"]}]`
- **THEN** 仅 `sec_ts` 这个 `oot-driver` 被纳入编译
- **AND** 同包内未被选中的 `oot-driver`（如 `sgm37604a`）MUST NOT 被编译

#### Scenario: 引用不存在的包

- **WHEN** board 配置 `packages: ["does-not-exist"]`
- **THEN** 构建失败
- **AND** 错误信息包含包名 `does-not-exist`

#### Scenario: 未声明 packages 保持兼容

- **WHEN** board 配置未声明 `packages` 或为空列表
- **THEN** kernel / boot / rootfs 组件保持现有不启用包时的构建行为

### Requirement: 按类型分发到既有流水线

构建引擎 MUST 按 component 的 `type` 把包内容分发到对应的既有构建流水线：`oot-driver` MUST 复用 OOT 模块编译与安装路径（`make M=<本地包目录>` → strip → 装入 `lib/modules/.../updates/`）；`devicetree` MUST 复用 device-tree-overlay 的 cpp+dtc 流水线产出 `.dtbo`；`deb` MUST 复用 rootfs deb 安装路径。`oot-driver` 的源目录 MUST 解析为包内本地路径，MUST NOT 要求声明 git 源。

#### Scenario: oot-driver 编译并安装

- **WHEN** 启用的包含 `oot-driver` 名为 `sec_ts`、`dir: "driver/sec_ts"`、`ko_pattern: ["sec_ts.ko"]`
- **THEN** 构建系统在 `components/packages/<pkg>/driver/sec_ts` 处以 `make M=` 对内核源码树编译
- **AND** 产出的 `sec_ts.ko` 经 strip 安装到 `lib/modules/<release>/updates/`

#### Scenario: devicetree 编译为 dtbo

- **WHEN** 启用的包含 `devicetree` component，且其对当前 board 声明了对应 `.dtso`
- **THEN** 该 `.dtso` 经 cpp+dtc 编译为 `.dtbo` 并纳入 boot 分区 overlay 打包集合

### Requirement: 按需编译

`oot-driver` 类型 MUST 支持按需编译：仅当某 board 的启用配置实际选中该驱动时才编译。包内携带但未被任何启用配置选中的 `oot-driver` MUST NOT 被编译，也 MUST NOT 安装其 `.ko`。

#### Scenario: 未选中的驱动不编译

- **WHEN** `meizu-e3-panel` 包内含 `sec_ts` 与 `sgm37604a` 两个 `oot-driver`，board 仅选中 `sec_ts`
- **THEN** `sgm37604a` MUST NOT 被编译
- **AND** rootfs 的 `lib/modules/<release>/updates/` 不包含 `sgm37604a.ko`

### Requirement: 包内容纳入增量哈希

启用包的 board，其包目录内容（驱动源、dtso、固件等被启用 component 涉及的文件）MUST 纳入对应组件（kernel / boot / rootfs）的内容哈希。包内被启用内容变更 MUST 触发相应组件的增量重建；未启用 component 的内容变更 MUST NOT 触发重建。

#### Scenario: 驱动源变更触发 kernel 重建

- **WHEN** 已启用 `sec_ts` 的 board 修改了 `components/packages/meizu-e3-panel/driver/sec_ts` 内任一源文件
- **THEN** 下次构建 kernel 组件因内容哈希变化而重建该 OOT 模块

#### Scenario: dtso 变更触发 boot 重建

- **WHEN** 已启用 panel overlay 的 board 修改了对应 `.dtso`
- **THEN** 下次构建 boot/device-tree-overlay 组件因内容哈希变化而重新编译该 `.dtbo`
