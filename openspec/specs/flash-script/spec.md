### Requirement: 刷写主入口脚本
`scripts/flange-flash.sh` SHALL 作为宿主机刷写的主入口脚本，解析命令行参数，从 `target/<board>/image/` 读取产物，调用平台对应的刷写模块执行操作。

#### Scenario: 整盘 dd 刷写
- **WHEN** 执行 `./scripts/flange-flash.sh --board radxa-zero3w --raw --device /dev/sdX`
- **THEN** 将 `target/radxa-zero3w/image/<board>_firmware_<date>.img` 通过 dd 写入 `/dev/sdX`

#### Scenario: USB 分段刷写
- **WHEN** 执行 `./scripts/flange-flash.sh --board radxa-zero3w`
- **THEN** 调用平台对应的刷写工具（Rockchip: upgrade_tool）执行 USB 刷写流程：`upgrade_tool DB miniloader.bin` → `upgrade_tool WL 0 firmware.img` → `upgrade_tool RD`

#### Scenario: 组件级刷写
- **WHEN** 执行 `./scripts/flange-flash.sh --board radxa-zero3w --component kernel`
- **THEN** 仅刷写 boot 分区（包含内核和 DTB）

#### Scenario: 产物目录不存在
- **WHEN** `target/<board>/image/` 目录不存在
- **THEN** 输出错误信息提示先执行构建和收集

### Requirement: 平台刷写模块化架构
刷写脚本 SHALL 采用模块化架构，平台刷写逻辑通过 `scripts/flash/<platform>.sh` 实现，主脚本通过 source 加载。

#### Scenario: Rockchip 平台刷写模块
- **WHEN** 检测到目标板为 Rockchip 平台
- **THEN** 加载 `scripts/flash/rockchip.sh` 执行刷写

#### Scenario: 新增平台支持
- **WHEN** 需要支持 Allwinner 平台刷写
- **THEN** 只需新增 `scripts/flash/allwinner.sh`，无需修改主脚本

### Requirement: 刷写工具检测
刷写脚本 SHALL 在执行前检测所需的刷写工具是否已安装，未安装时提供安装指引。

#### Scenario: upgrade_tool 不存在
- **WHEN** Rockchip 平台刷写时 `tools/rockchip/upgrade_tool/upgrade_tool` 不存在
- **THEN** 输出错误信息并提示该工具为项目内置工具，需检查项目完整性

#### Scenario: dd 工具检查
- **WHEN** 使用 `--raw` 模式刷写
- **THEN** 检查 dd 命令可用（通常系统自带）

### Requirement: 刷写安全确认
刷写脚本 SHALL 在执行破坏性写入操作前要求用户确认，防止误刷错误设备。

#### Scenario: dd 刷写确认
- **WHEN** 执行 `--raw --device /dev/sdX` 刷写
- **THEN** 显示目标设备信息并要求用户输入确认

#### Scenario: USB 刷写设备检测
- **WHEN** 执行 USB 分段刷写
- **THEN** 检测目标设备是否处于 Maskrom/Loader 模式，未检测到时提示用户操作
