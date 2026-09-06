---
title: 子系统索引
type: index
updated: 2026-09-05
---

# 子系统索引

先读[架构总览](../concepts/架构总览.md)。完整修改边界见[构建系统设计](../../docs/build-system-design.md)。

- [路径与工作区](路径锚点-paths.md)：工具根、项目根、输出根和 Target 的归属。
- [配置子系统](配置子系统.md)：Jsonnet 求值、严格 schema、来源与语义校验。
- [构建引擎 BuildEngine](构建引擎-BuildEngine.md)：TaskPlan 依赖调度与产物发布。
- [ComponentBuilder 基类](ComponentBuilder-基类.md)：平台配方生命周期。
- [源码管理 SourceManager](源码管理-SourceManager.md)：共享下载与目标独立工作树。
- [缓存系统](缓存系统.md)：输入指纹、有效清单与重建解释。
- [Docker 执行封装](Docker-执行封装.md)：容器执行与外部工作区挂载。
- [Docker 构建环境](Docker-构建环境.md)：工具链、multiarch 和构建依赖。
- [chroot 上下文](chroot-上下文.md)：挂载与清理。
- [deb 打包引擎](deb-打包引擎.md)：安装树转 Debian 包。
- [输出系统 BuildOutput](输出系统-BuildOutput.md)：分层终端输出与持久日志。
- [scaffold 生成器](scaffold-生成器.md)：生成 App/Package 工程。
- [Recovery 宿主 CLI](recovery-host-CLI.md)：ADB 维护编排。
