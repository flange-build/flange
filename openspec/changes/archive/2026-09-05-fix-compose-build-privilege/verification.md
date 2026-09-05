# Compose 构建权限修复验证记录

验证日期：2026-09-05。真实容器环境：Docker Compose v5.1.2、Docker 29.4.0。

## 已完成检查

- 定向单元测试：`tests/builder/test_docker_extra_mounts.py` 与
  `tests/builder/test_docker_capture.py` 合计 **22 passed**。覆盖本次权限参数与宿主同名变量的
  true/false 组合、宿主环境不变、原有挂载、容器内执行及输出捕获行为。
- Compose 配置检查：分别以 `FLANGE_BUILD_PRIVILEGED=false` 和 `true` 解析 JSON 配置，
  `build` 服务的有效 `privileged` 值均与请求一致。未设置开关时，Compose JSON 输出省略
  值为 `false` 的默认属性；按 `service.get('privileged', False)` 读取为非特权。
- 真实 Docker 验证：以下命令获得 **4 passed、5 deselected**。其中新增的两个参数化用例通过
  `CapEff`（有效能力位）检查 `CAP_SYS_ADMIN`，并实际尝试挂载、写入及卸载临时 tmpfs
  （内存文件系统）；特权调用成功，普通调用保持无挂载权限。两个既有 App 用例验证 Make 与
  CMake 的 AArch64 外部 App 生命周期，均覆盖首次交叉编译、缓存命中及产物权限损坏后重建。

  ```bash
  FLANGE_RUN_DOCKER_TESTS=1 pytest tests/integration/test_docker_privilege.py tests/integration/test_oot_lifecycle.py -k '真实容器 or (make and aarch64)'
  ```

- Ruff 的 `E4,E7,E9,F` 检查通过；`git diff --check` 通过。
- `openspec validate fix-compose-build-privilege --strict` 通过。
- 全量 pytest：**1734 passed、9 skipped，223.46 秒，退出码 0**。日志保存于本次验证宿主的
  `/tmp/flange-compose-privilege-full.log`；默认跳过的真实 Docker 用例按上述显式命令另行执行。
- 归档后 `openspec validate --all --strict`：**77 passed、0 failed**；
  `.venv/bin/python -m pytest tests/openspec -q`：**134 passed**。

## 实现与规格核对

- `docker-compose.yml` 在服务运行时属性声明
  `privileged: ${FLANGE_BUILD_PRIVILEGED:-false}`，没有将其放到镜像构建配置中。
- `DockerRunner._run_docker` 不再追加 `--privileged`，每次以新的环境字典显式覆盖本次开关；
  `capture=True` 仅改变输出处理，`run_privileged` 委托给 `run(..., privileged=True)`。
- `builder/commands.py` 的 `_system` 构建调用继续显式传入 `privileged=True`；普通 App、Package
  构建及 `flange shell` 使用同一 `run` 路径的非特权默认值。已在容器中的调用沿用既有直接执行行为。
- `openspec archive fix-compose-build-privilege --yes` 已向 `docker-build-env` 主规格同步三项新增要求，
  并将本变更归档到 `2026-09-05-fix-compose-build-privilege`；六项任务全部完成。

## 验证范围

未执行完整系统镜像编译或设备刷写，本记录不作为目标固件、板卡启动或硬件功能验收。
