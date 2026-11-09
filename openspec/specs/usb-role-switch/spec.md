# usb-role-switch Specification

## Purpose

定义 device ↔ host 角色切换的平台抽象：平台探测顺序、各平台 sysfs 节点契约、取值归一化、切换原语与不支持平台的显式报错行为。

## Requirements
### Requirement: 平台探测


系统 SHALL 通过探测 sysfs 节点确定当前平台的 USB 角色切换方式，按以下顺序依次尝试，命中即采用：

1. `/sys/class/usb_role/<controller>-role-switch/role` —— mainline dwc3 的标准 USB role switch 接口，取值 `none` / `host` / `device`
2. `/sys/devices/platform/*/otg_mode` —— Rockchip BSP 的私有接口

探测逻辑 SHALL 与切换原语分离，使新增平台只需扩展探测表。

Type-C 的 `/sys/class/typec/port*/data_role` 本版 MUST NOT 纳入探测链。

#### Scenario: mainline dwc3 平台探测命中

- **WHEN** 系统存在 `/sys/class/usb_role/` 下的 role-switch 节点
- **THEN** 探测返回该节点路径及 mainline 后端，角色查询与切换均通过该节点进行

#### Scenario: Rockchip BSP 平台探测命中

- **WHEN** 系统不存在 `/sys/class/usb_role/` 节点，但存在 `otg_mode` 平台节点
- **THEN** 探测返回该节点路径及 Rockchip 后端

#### Scenario: Type-C 节点不参与探测

- **WHEN** 系统仅存在 `/sys/class/typec/port0/data_role` 而无前两类节点
- **THEN** 探测判定为不支持，不尝试通过 Type-C 节点切换角色

### Requirement: 不支持平台的显式报错


当所有探测项均未命中时，系统 SHALL 明确返回「本平台不支持 role 切换」的错误，并指明已尝试过的节点路径。

系统 MUST NOT 静默失败 —— 即不得出现「命令返回成功但硬件角色未改变」的情形。

#### Scenario: 无可用节点时报错

- **WHEN** 在不存在任何已知 role 切换节点的平台上请求切换角色
- **THEN** 返回失败，错误信息包含「不支持」字样及已尝试的节点路径列表，不对硬件做任何写入

#### Scenario: 查询角色在不支持平台上的行为

- **WHEN** 在不支持 role 切换的平台上查询当前角色
- **THEN** 返回明确的「不支持」状态，而非伪造的默认值

### Requirement: 角色查询


系统 SHALL 支持查询当前 USB 角色，返回值 SHALL 归一化为 `host` / `device` / `none` 三者之一，屏蔽各平台节点的原始取值差异。

#### Scenario: 归一化 mainline 取值

- **WHEN** `/sys/class/usb_role/<ctrl>-role-switch/role` 内容为 `device`
- **THEN** 查询返回 `device`

#### Scenario: 归一化平台私有取值

- **WHEN** Rockchip `otg_mode` 节点返回该平台的私有表示
- **THEN** 查询将其映射为 `host` / `device` / `none` 中的对应值

### Requirement: 角色切换原语


系统 SHALL 提供设置 USB 角色的原语，接受归一化取值 `host` / `device`，由后端翻译为平台节点的具体写入值。

切换后 SHALL 回读节点校验实际生效值；回读值与目标值不符时 SHALL 返回失败。

#### Scenario: 切换成功并通过回读校验

- **WHEN** 在支持的平台上请求切换到 `host`，写入后回读节点得到 `host`
- **THEN** 原语返回成功

#### Scenario: 回读不符时判定失败

- **WHEN** 写入 role 节点后回读得到的值与目标值不符
- **THEN** 原语返回失败并报告期望值与实际值，不向上层谎报成功

#### Scenario: 切换原语不感知 gadget 状态

- **WHEN** 检查角色切换原语的实现
- **THEN** 其中不包含 gadget 启停逻辑；gadget 与 role 的先后顺序由上层服务编排
