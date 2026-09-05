## ADDED Requirements

### Requirement: 构建容器权限必须通过合法 Compose 服务配置传递

DockerRunner MUST 使用 Docker Compose（容器编排）支持的服务配置传递容器特权模式，
MUST NOT 将仅属于 `docker run` 的 `--privileged` 选项追加到 `docker compose run`。
`docker-compose.yml` 中 `build` 服务的运行时 `privileged` 属性 MUST 默认关闭，
并允许 DockerRunner 为本次调用明确选择。

#### Scenario: 特权容器启动命令可由 Compose 解析
- **WHEN** DockerRunner 请求以特权模式启动构建容器
- **THEN** Compose 命令不包含 `--privileged`，服务配置将本次容器的 `privileged` 解析为 `true`
- **AND** 容器不会因该选项触发 `unknown flag: --privileged`

#### Scenario: 服务配置缺省关闭特权模式
- **WHEN** 未显式提供构建容器的特权开关并解析 Compose 配置
- **THEN** `build` 服务以非特权模式运行；解析结果可显式输出 `privileged: false` 或省略该默认属性

### Requirement: 系统构建必须保留所需容器权限

系统镜像、rootfs 等需要 mount（挂载）能力的构建调用 MUST 显式启用特权模式。
Compose 参数兼容性修复 MUST 保留这些操作的实际容器权限，不得通过移除权限使其在后续步骤失败。

#### Scenario: 系统构建容器具备挂载能力
- **WHEN** 在允许特权容器的 Docker 主机执行需要挂载文件系统的系统构建调用
- **THEN** 该次调用启动的容器启用特权模式，并能完成临时文件系统的挂载与卸载

### Requirement: 容器权限必须按调用隔离

所有通过 `DockerRunner.run` 启动 Compose 的调用 MUST 在各自子进程环境中
按本次 `privileged` 参数显式设置 `FLANGE_BUILD_PRIVILEGED` 为 `true` 或 `false`，
MUST NOT 修改宿主进程环境或让宿主同名变量覆盖调用参数。
`capture=True` 的输出捕获调用和通过 `run_privileged` 委托的调用 MUST 遵循相同权限选择规则。
普通 App、Package 编译 MUST 默认使用非特权容器。

#### Scenario: 普通编译不继承宿主特权开关
- **WHEN** 宿主 `FLANGE_BUILD_PRIVILEGED=true`，而普通 App 或 Package 编译未请求特权模式
- **THEN** 本次 Compose 子进程收到 `FLANGE_BUILD_PRIVILEGED=false`，容器保持非特权
- **AND** 宿主进程原有环境变量不变

#### Scenario: 系统调用不继承宿主关闭开关
- **WHEN** 宿主 `FLANGE_BUILD_PRIVILEGED=false`，而 DockerRunner 本次请求特权模式
- **THEN** 本次 Compose 子进程收到 `FLANGE_BUILD_PRIVILEGED=true`
- **AND** 宿主进程原有环境变量不变

#### Scenario: 相邻调用互不污染
- **WHEN** 先执行特权调用，再执行普通调用，或以相反顺序执行
- **THEN** 每个容器均按各自调用参数选择权限，输出捕获或 `run_privileged` 委托不改变该规则
