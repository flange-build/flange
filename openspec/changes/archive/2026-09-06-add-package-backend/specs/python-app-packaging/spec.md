## MODIFIED Requirements

### Requirement: custom vendor App SHALL 支持多个完整 DEB 输出

AppSpec MUST 继续接受 `build.deb_outputs`，仅允许用于 `app.type=vendor` 且 `build.system=custom`。每项 MUST 为安全、唯一、无 glob 的 `.deb` 文件名。该兼容声明 SHALL 规范化为 DEB 后端的 runtime 输出，与新 `packaging` 段 MUST NOT 混用。AppBuilder SHALL 通过后端验证并提取所有声明包，不生成 wrapper DEB；未声明外部输出时 SHALL 根据 AppSpec 与安装树调用默认打包流程。

#### Scenario: 多 DEB 输出成功
- **WHEN** custom vendor App 声明三个 build.deb_outputs 并生成对应文件
- **THEN** DEB 后端校验、保留三包并提取依赖安装树
- **AND** rootfs 安装全部三个 runtime 包，保持兼容语义

#### Scenario: 声明输出缺失
- **WHEN** App 未生成任一声明包
- **THEN** 构建失败并指出缺失文件，不替换上次成功产物

#### Scenario: 非法输出声明
- **WHEN** deb_outputs 含路径、glob、重复文件名，或用于非 vendor/custom App
- **THEN** AppSpec 在执行命令前拒绝配置
