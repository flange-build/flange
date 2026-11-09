## ADDED Requirements

### Requirement: 首页直接展示板卡覆盖

README MUST 在快速开始之前直接列出当前仓库内置板卡的名称、SoC（片上系统）及板卡文档链接，并按厂商平台分组。
清单与总数 MUST 对照 `components/board/*/config.jsonnet` 核验，MUST 明确配置覆盖不等同于全部功能实机验收。

#### Scenario: 判断自己的开发板是否有配置
- **WHEN** 读者打开 README 查找板卡
- **THEN** 无需跳转即可看到具体板名与芯片，并能直接进入相应板卡记录
- **AND** 不会把配置总数理解成当前版本已完整验收的设备数量
