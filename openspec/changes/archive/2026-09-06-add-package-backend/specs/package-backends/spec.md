## ADDED Requirements

### Requirement: App 打包 SHALL 通过格式后端

通用 AppBuilder SHALL 委托已注册 PackageBackend 规划、生成或导入包，MUST NOT 直接执行 DEB 命名、打包或 dpkg-deb 逻辑。首个实现 SHALL 为 DEB，未知格式 MUST 在解析/计划阶段失败。Ubuntu APT 编译依赖 SHALL 独立于交付格式选择。

#### Scenario: 默认库打包
- **WHEN** lib App 未声明完整外部输出
- **THEN** DEB 后端生成独立 runtime 和 development 包，开发文件与未带版本的共享库链接不进入运行包

### Requirement: 外部交付物 SHALL 显式描述角色

`packaging.format` SHALL 选择格式，`packaging.outputs` SHALL 精确列出唯一 file 和 runtime/development role。路径、glob、未知字段、角色、格式和与 deb_outputs 的混用 MUST 被拒绝。完整外部包 SHALL 可用于 service/exec/lib/test/vendor，与 build.system 解耦；amp/staging MUST 不接受包交付配置。

#### Scenario: CPack 组件包
- **WHEN** service App 输出 runtime 与 development 两个完整 DEB
- **THEN** 系统保留两包原始字节和维护脚本，通过 DEB 后端验证架构与安装树，不生成 wrapper 包

### Requirement: 包角色 SHALL 贯穿依赖与消费

所有声明包 SHALL 进入可验证报告与缓存清单。所有包的文件 SHALL 合并为下游编译安装树；默认部署/rootfs SHALL 仅消费 runtime 闭包。App 运行入口 MUST 来自 runtime 包。包路径冲突、缺失、错误架构或无效运行入口 MUST 阻止原子发布并保留上次成功产物。

#### Scenario: 开发包只供构建使用
- **WHEN** 下游 App 依赖一个包含 runtime/development 包的服务或库
- **THEN** 编译前缀提供开发头文件、库与元数据，默认安装清单排除 development 包

#### Scenario: 开发包被篡改
- **WHEN** 任意开发包或其角色元数据变化
- **THEN** 缓存/报告验证失败，不能将旧结果冒充成功

### Requirement: CLI SHALL 展示全部交付包

App 构建的机器输出和终端 SHALL 展示每个包的格式、角色和准确路径，MUST NOT 只展示 runtime 而隐藏开发交付物。

#### Scenario: 两包构建结果
- **WHEN** CPack App 完成两包交付
- **THEN** CLI 分别显示运行包与开发包，报告包含两包的可验证身份
