## Why

`flange build` 将 Docker Engine（容器引擎）的 `--privileged` 参数传给不接受该参数的
`docker compose run`，导致容器启动前报 `unknown flag: --privileged`。
系统镜像制作仍需要挂载等特权能力，因此需要通过合法的 Compose（容器编排）服务配置按调用启用。

## What Changes

- 将构建容器的特权模式改为 Compose 服务属性，由 DockerRunner 按本次调用显式选择。
- 系统镜像与 rootfs 保留所需权限；普通 App、Package 编译默认非特权，且不受宿主同名环境变量干扰。
- 补充权限传递、Compose 解析与真实容器的回归检查，并同步项目规格和开发指南。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `docker-build-env`：规定容器特权模式的 Compose 兼容性、调用隔离与系统构建权限要求。

## Impact

影响 `builder/docker.py`、`docker-compose.yml`、对应 DockerRunner 测试、`ProjectSpec.md` 与开发指南。
保持现有构建入口和 Docker 镜像内容，无需新增依赖。

## 非目标

- 不修改目标配置、编译工具链、组件依赖或缓存算法。
- 不全局启用所有构建容器的特权模式。
- 不更改宿主权限、跨架构注册或设备刷写流程。
