## ADDED Requirements

### Requirement: 已注册的本地 OOT App 在整体构建容器中必须可见

构建系统 SHALL 在 FINAL_CONFIG 通过 `external_apps[*].local_path` 或
`external_app_dirs` 引用项目根外 App 时，为所有构建阶段挂载所需 OOT 源。若 App 位于 git
worktree 内，构建系统 SHALL 挂载 worktree root 而不只挂载 App 子目录，以支持受约束的
本地 package 依赖。宿主 source 与容器 target SHALL 按各自项目根的相同相对位置解析。

#### Scenario: AMP App 引用同一 Fluxion worktree 的 Swift targets

- **WHEN** `amp.app` 的 local_path 位于 Fluxion worktree 子目录，Package.swift 引用该
  worktree 根的本地 package
- **THEN** 外层容器挂载整个 Fluxion worktree，AMP builder 能同时读取 App 和依赖源码

#### Scenario: OOT 路径不存在

- **WHEN** FINAL_CONFIG 选择的 local_path 在宿主不存在
- **THEN** shell 在启动 Docker 前以中文错误终止，不创建空 bind mount

### Requirement: amp.app 必须复用 app-registry 查找

Rockchip AMP builder SHALL 通过 `SourceManager.ensure_app` 解析 `amp.app`，遵循仓内、
`external_apps`、`external_app_dirs` 的既有优先级。解析后 MUST 校验 app.yaml 名称与
`app.type=amp`；hal mode 只接受 cmake，rt-thread mode 只接受 scons。

#### Scenario: local_path 提供 RT-Thread AMP App

- **WHEN** `external_apps[amp_name].local_path` 指向合法 `type: amp`、`build.system: scons`
  的目录
- **THEN** `flange build amp` 叠加该目录，而不是继续查找
  `components/app/<amp_name>`

#### Scenario: service 被错误选为 AMP App

- **WHEN** local_path 的 app.yaml 声明 `type: service`
- **THEN** AMP builder 在复制或编译源码前拒绝并指出类型错误

### Requirement: 本地 OOT 源修改不得命中旧构建缓存

当 app 或 amp 组件消费 local_path/external_app_dirs 源时，构建缓存 SHALL 把该组件视为
开发态本地输入，并使依赖它的 rootfs、recovery 或 image 同步失效。git 来源 SHALL 至少把
注册 ref 和已获取源码内容纳入哈希。

#### Scenario: 修改 OOT AMP Swift 文件

- **WHEN** 用户修改 local_path 中的 Swift 源后再次构建 amp 或 image
- **THEN** 缓存不复用旧 amp.img，新的源必须重新编译并进入下游镜像
