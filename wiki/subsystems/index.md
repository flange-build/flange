---
title: 子系统索引
type: index
updated: 2026-04-26
---

# 子系统索引

`builder/` 下的实现模块，被组件构建器与策略类调用。

- [[配置子系统]] — 三层继承 + condition-markers + apps 注册 + 校验
- [[构建引擎 BuildEngine]] — 依赖图 + 调度 + cache 注入
- [[ComponentBuilder 基类]] — 阶段生命周期框架
- [[Docker 执行封装]] — 容器内执行命令
- [[源码管理 SourceManager]] — git / tarball 克隆与缓存
- [[缓存系统]] — 哈希接口与阶段缓存
- [[chroot 上下文]] — mount / umount 自动管理
- [[deb 打包引擎]] — pure python tarfile + ar
- [[输出系统 BuildOutput]] — L1/L2/L3 输出 + 颜色 + spinner
- [[scaffold 生成器]] — App 骨架生成
- [[路径锚点 paths]] — PROJECT_ROOT / COMPONENTS_ROOT / BUILD_ROOT
- [[recovery-host-CLI]] — 宿主机 ADB 编排
