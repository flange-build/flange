## Context

DockerRunner 的 `privileged=True` 当前直接追加 `--privileged`，但本机 Docker Compose
v5.1.2 的 `run` 不支持此参数。系统构建在启动容器前失败；去掉参数而不传递服务权限，又会使
rootfs 的 mount（挂载）等步骤缺少能力。已有普通 App、Package 编译默认非特权的边界应继续保留。

## Goals / Non-Goals

**目标：** 修复 Compose 参数错误，保持系统构建所需能力，并让每次调用的权限选择可验证、互不干扰。

**非目标：** 不调整组件图、缓存、镜像工具链、binfmt（跨架构执行注册）或设备操作。

## Decisions

1. 在 `docker-compose.yml` 的 `build` 服务上声明
   `privileged: ${FLANGE_BUILD_PRIVILEGED:-false}`。这是容器运行时服务属性，
   不属于服务的 `build` 镜像构建配置；默认值关闭特权模式。
2. DockerRunner 为每次 Compose 子进程创建环境副本，并依据本次 `privileged` 参数将
   `FLANGE_BUILD_PRIVILEGED` 显式设置为 `true` 或 `false`。不修改宿主 `os.environ`，
   不继承宿主同名变量的权限选择，也不通过容器内的 `-e` 环境变量配置服务权限。
3. 所有通过 `DockerRunner.run` 启动 Compose 的调用共用权限选择语义，包含
   `capture=True`（捕获输出）和委托给 `run` 的 `run_privileged`。系统构建继续显式申请所需权限，
   普通 App、Package 默认非特权。继续保留既有 Compose 挂载、环境、TTY（终端）与输出行为，
   不新增执行入口。
4. 不使用全局 `privileged: true`，避免普通编译被扩大权限；不改为独立 `docker run`，
   避免重复维护服务挂载与镜像配置。当前修复不引入多套服务或临时 Compose 文件。

## Risks / Trade-offs

- 系统镜像制作本身依赖 Docker 主机允许特权容器 → 保留现有权限需求，并在真实 Docker
  中检查挂载能力；此修复不替代宿主环境准备。
- 环境变量容易被宿主或相邻调用污染 → 对 true/false 两个方向做回归测试，核对所有 Compose
  启动均通过同一执行路径创建子进程环境副本。
- 模拟子进程测试无法证明 Compose 接受配置 → 同时检查 Compose 配置解析和真实容器的权限行为。

## Migration Plan

同步更新 Python 执行封装、Compose 文件、测试和文档。镜像内容不变，无需重建构建镜像或迁移工作区。
如需回退，必须成对回退执行封装与 Compose 服务属性，避免二者权限契约不一致。

## Open Questions

无。
