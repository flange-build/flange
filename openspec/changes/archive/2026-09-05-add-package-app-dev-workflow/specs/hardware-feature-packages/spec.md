## MODIFIED Requirements

### Requirement: 包清单契约

仓库内硬件特性包 MUST 位于 `components/packages/<pkg>/` 目录；ad-hoc Package MAY 位于任意可访问目录。
两者 MUST 提供一个 `package.py`，导出名为 `PACKAGE` 的 dict。`PACKAGE` MUST 包含 `name`（kebab-case
字符串，MUST 与目录名一致）与 `components`（列表）。`components` 中每一项 MUST 是 dict 且 MUST 含
`type` 字段，`type` 的取值 MUST 属于 `oot-driver` / `devicetree` / `vendor` 之一；未知 `type` MUST 使
构建失败并在错误信息中给出该 `type` 与候选集合。ad-hoc 清单旁的 `config.jsonnet` MUST NOT 被隐式加载。

#### Scenario: 合法包清单被加载

- **WHEN** `components/packages/foo/package.py` 导出
  `PACKAGE = {"name": "foo", "components": [{"type": "oot-driver", "name": "bar", "dir": "driver/bar", "ko_pattern": ["bar.ko"]}]}`
- **THEN** 构建系统成功加载该包并识别出 1 个 `oot-driver` 类型 component

#### Scenario: 未知 component 类型

- **WHEN** 某 component 的 `type` 为 `firmware`（不在合法集合内）
- **THEN** 构建失败
- **AND** 错误信息包含非法值 `firmware` 与候选集合 `oot-driver` / `devicetree` / `vendor`

#### Scenario: name 与目录名不一致

- **WHEN** Package 目录名为 `foo`，但 `PACKAGE["name"]` 为 `bar`
- **THEN** 构建失败
- **AND** 错误信息指出 `name` 与目录名不一致

#### Scenario: 仓库外清单不隐式合并配置

- **WHEN** `/work/foo/package.py` 合法且同目录含 `config.jsonnet`
- **THEN** `flange package build /work/foo` 只加载显式 `package.py`
- **AND** `config.jsonnet` 不进入当前 board/product/variant 配置

## ADDED Requirements

### Requirement: Package SHALL 可按名称或路径加载

board opt-in SHALL 继续按仓库内名称加载 Package；资源优先 package 命令 SHALL 额外接受绝对路径、相对
调用者 cwd 的路径和当前目录。路径目标 MUST 是含 `package.py` 的目录，解析后 SHALL 使用同一套清单校验。

#### Scenario: 相对路径基于调用者 cwd

- **WHEN** 用户在 `/work` 执行 `flange package build ./foo`
- **THEN** 加载 `/work/foo/package.py`，而不是相对 flange project root 解析
