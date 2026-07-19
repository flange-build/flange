## Why

Fluxion 已能把 FTS 编译为固定容量的 Embedded Swift Runtime 计划，但尚无一条可以把该
产物部署到真实 AMP 设备、控制电机并回传观测数据的构建链。ATK-RK3506B 已有经过实机
验证的 U-Boot/FIT → CPU2 RT-Thread、mailbox、RPMsg 和 Linux 启动基线，适合作为第一块
真实目标板。

当前阻断不是 RK3506 AMP 基础设施，而是 Flange 的 AMP builder 仍把 `amp.app` 硬编码为
`components/app/<name>`。现有 `external_apps` 只对普通 Linux App 生效；整体构建又运行在
只挂载 `/workspace` 的外层容器中，因此 Fluxion 仓库里的 OOT AMP App 和 Linux bridge
均不可见。缓存也可能复用旧的 OOT 产物。

## What Changes

- Rockchip AMP builder 统一通过 `SourceManager.ensure_app` 解析 `amp.app`，并校验
  `app.type` 与 mode/build.system 契约。
- AMP/App 缓存识别 `external_apps.local_path` 与 `external_app_dirs`；本地开发态 OOT
  源强制使自身及下游失效，git OOT 源把注册信息和可用源码内容纳入哈希。
- `envsetup.sh` 在外层 `docker compose run` 前解析 FINAL_CONFIG，把外部 App 所在 git
  worktree 映射到容器内相同相对位置，支持 OOT Swift package 的本地依赖。
- ATK-RK3506B 新增 `fluxion` product，保留 `default` RPMsg echo 救援基线；fluxion
  product 选择 Fluxion CPU2 AMP App，并把 Linux RPMsg/Web bridge 安装进 rootfs。
- Fluxion OOT App 定义固定小端二进制协议、控制租约、ACK、遥测快照和失败关闭 board
  hook。FTS 只在主机编译，实时核运行静态计划。

## Capabilities

### New Capabilities

- `fluxion-rk3506-deployment`：规范 RK3506 CPU2 Runtime、Linux bridge、RPMsg 线协议、
  控制租约、安全边界和 Web 对接。

### Modified Capabilities

- `amp-firmware-build`：`amp.app` 必须支持 app-registry 的完整 OOT 查找。
- `out-of-tree-app-build`：整体 component/image 构建必须在外层容器可见已注册的本地
  OOT App，而不只支持单独的 `flange build app <path>`。
- `build-cache`：本地 OOT AMP/App 修改不得命中旧组件或下游镜像缓存。
- `rockchip-atk-rk3506b`：新增不影响 default 的 fluxion product。

## Impact

- Flange 修改：
  - `builder/platforms/rockchip/amp.py`
  - `builder/platforms/rockchip/__init__.py`
  - `builder/cache.py`
  - `envsetup.sh`
  - `components/board/atk-rk3506b/config.py`
  - 对应测试与板级文档
- Fluxion 新增：
  - `Device/FlangeApps/rk3506_amp_fluxion_foc`
  - `Device/FlangeApps/fluxion_rpmsg_bridge`
- 非目标：
  - 不在 RT-Thread 上解析 FTS 文本或保存工作区布局。
  - 不通过 RPMsg 下发裸 MMIO、裸 PWM 或未校验插件代码。
  - 未确认功率板接线前不选择具体 PWM/ADC/编码器通道，不宣称完成真实电机带载验证。
  - 第一纵切不实现在线 PI/保护/电机参数热调；现有 Runtime 对这些参数仍是静态配置。
