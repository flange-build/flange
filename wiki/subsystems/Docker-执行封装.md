---
title: Docker 执行封装
type: subsystem
status: stable
sources:
  - builder/docker.py
  - docker/Dockerfile
  - docker/entrypoint.sh
related:
  - "[[ComponentBuilder 基类]]"
  - "[[构建引擎 BuildEngine]]"
updated: 2026-04-26
---

## TL;DR

`builder/docker.py` 的 `DockerRunner` 将所有编译命令路由至 Docker 容器内执行；自动挂载项目根目录、传递只读 SSH 密钥、将容器 stdout/stderr 转发给 `BuildOutput`。宿主机无需安装任何编译工具链。

## 关键设计要点

- **容器判断**：`_is_inside_container()` 检测 `/.dockerenv`；若已在容器内则直接 `subprocess` 运行，避免嵌套 Docker
- **Volume 策略**：`_run_docker` 挂载整个 PROJECT_ROOT（含 `.build/`），确保构建产物写回宿主机；SSH `~/.ssh` 以只读方式挂载供 git 认证
- **输出流转**：`_run_with_capture` 逐行读取 stdout 并调用 `output.feed_line()`，保持 spinner 与日志同步；`_run_direct` 则直连 tty 用于交互场景
- **特权构建**：`run_privileged` 加 `--privileged` 供 rootfs chroot 阶段（dpkg -i、mke2fs）使用
- **entrypoint 权限修正**：`docker/entrypoint.sh` 将容器内 UID/GID 对齐宿主机，避免产物归属 root
- **错误传播**：`DockerRunner.run` 检查返回码，非零时抛出 `BuildError`，由 `BuildEngine` 统一捕获展示

## 关键代码位置

- [`builder/docker.py:DockerRunner`](../../builder/docker.py) — 主类，L18
- [`builder/docker.py:DockerRunner.run`](../../builder/docker.py) — 统一入口，L33
- [`builder/docker.py:DockerRunner._run_docker`](../../builder/docker.py) — 容器执行，L123
- [`builder/docker.py:DockerRunner.run_privileged`](../../builder/docker.py) — 特权模式，L153
- [`builder/docker.py:_is_inside_container`](../../builder/docker.py) — 容器检测，L13
