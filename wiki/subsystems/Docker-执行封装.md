---
title: Docker 执行封装
type: subsystem
status: stable
sources:
  - builder/docker.py
  - builder/oot_mounts.py
  - docker-compose.yml
  - docker/entrypoint.sh
  - docs/development-guide.md
updated: 2026-09-05
---

# Docker 执行封装

DockerRunner（容器执行器）使用工具根的 `docker-compose.yml`，将目标编译、chroot 和镜像制作放入统一容器。
宿主负责入口、挂载和设备操作，不能把 USB 刷写混入构建配方。

工作区、工具根、输出根及外部 App/源码目录在最外层 Docker 调用中按同绝对路径挂载。
已经进入容器后，`run()` 直接执行子进程；此时不能再靠内层 `extra_mounts` 动态增加宿主目录。
外部来源必须先由工作区与资源解析器明确定位。

`run()` / `run_privileged()` 传递参数列表、工作目录与环境变量，并将命令输出交给 BuildOutput。
默认检查非零退出码并传播 BuildError；镜像身份由实际 Docker image inspect 取得，
不能只用 Dockerfile 内容代表已经运行的工具环境。

构建镜像使用 `linux/amd64`。ARM 宿主是否能运行取决于 Docker 的跨架构支持；
rootfs 的 ARM 程序还依赖 Linux 内核的 QEMU/binfmt 注册。
内核工作目录必须大小写敏感，容器不会自动修复宿主文件系统语义。
Python 初始化阶段若缺少 Jsonnet wheel（预编译包）可能需要宿主 C++ 工具，
目标代码仍只在容器中编译。

安装、镜像准备、Git 凭据和环境排障统一见[开发指南](../../docs/development-guide.md)；
工具链内容见[Docker 构建环境](Docker-构建环境.md)。
