## Context

flange 当前的构建链路已经包含 `kernel`、`bootloader`、`app`、`rootfs`、`boot`、`image` 等组件，构建产物收集到 `.build/target/<board>/<product>/<variant>/`。Rockchip 和 Allwinner A733 的 boot 分区都通过 extlinux 启动内核，rootfs 分区由 `root=LABEL=rootfs` 或固定 PARTUUID 定位。刷写侧已有 Python 化的 `builder/flash.py` 方向，`flash-config.json` 可以把构建时的分区布局和镜像映射冻结到 target 目录。

用户希望新增一个 recovery 引导：设备进入 recovery 后，可通过 USB 线缆执行系统在线烧录、备份、刷写分区等操作，不依赖网线或 Wi-Fi。项目已经有 `adbd` App 和 USB gadget 配置，适合作为首版线刷 transport。

## Goals / Non-Goals

**Goals:**

- 提供独立 recovery 分区和 `recovery.img`，基于 Ubuntu base 构建完整一点的维护系统。
- normal 系统和 recovery 系统共享内核/DTB，boot 分区提供 normal 与 recovery 两个 extlinux 启动入口。
- 宿主机新增 `flange recovery` 命令组，首版通过 ADB over USB 编排 recovery 操作。
- recovery 系统内提供 `recoveryctl`，负责真实分区识别、备份、写入、校验和重启。
- 分区事实源来自 `partitions.entries` 和构建生成的 `recovery-config.json`，避免 recovery 内硬编码设备分区。
- 保持 transport 可替换：后续可加 USB DFU 或自定义 USB 协议，不重写设备端分区逻辑。

**Non-Goals:**

- 不实现 Ethernet、Wi-Fi、HTTP Web UI 或其他网络烧录。
- 不实现 OTA、A/B 分区、增量包或后台自动升级。
- 不在首版实现 USB DFU 或自定义 USB 协议。
- 不让 recovery 修改自身分区，除非后续单独设计 recovery 自升级流程。
- 不依赖宿主机在 Docker 容器内访问 USB；线刷仍在宿主机执行。

## Decisions

### 决策 1: recovery 是独立分区和独立 rootfs

新增 `recovery` 分区，构建产物为 `recovery/recovery.img`，文件系统 label 为 `recovery`。它不混入 normal rootfs，也不复用 normal rootfs 的运行时状态。

**理由**: normal rootfs 损坏时仍需要一个可启动维护环境；独立分区也能避免在线刷写 rootfs 时覆盖当前运行系统。

**替代方案**: 把 recovery 工具安装进 normal rootfs。缺点是 rootfs 损坏时不可用，刷写 rootfs 时也会破坏执行环境。

### 决策 2: 新增 `recovery` 构建组件

组件依赖图增加：

```text
kernel       ┐
app          ├── recovery ┐
bootloader   ┘            │
boot         ─────────────┤
rootfs       ─────────────┤
                           └── image
```

`recovery` 组件复用 rootfs 构建基础能力，但使用独立的 `config["recovery"]` profile。首版 package 集合包含 `systemd`、`udev`、`adb` 所需运行时、`python3-minimal`、`util-linux`、`e2fsprogs`、`dosfstools`、`parted`、`gptfdisk`、`zstd`、`coreutils` 等维护工具，并安装 `adbd` 和 `recoveryctl`。

**理由**: 构建缓存、产物收集和平台策略继续遵循现有 ComponentBuilder 模型；recovery 可以按内容哈希独立增量构建。

**替代方案**: 在 rootfs builder 内用参数分支同时生成 rootfs 和 recovery。缺点是组件边界不清晰，缓存和测试更难隔离。

### 决策 3: extlinux 双入口，bootonce 通过修改 boot 分区默认项实现

boot 分区生成的 `extlinux.conf` 包含两个 label：

```text
label flange
  append root=LABEL=rootfs ...

label flange-recovery
  append root=LABEL=recovery ...
```

`flange recovery enter` 在 normal 系统可通过 ADB 访问时，调用设备端 helper 原子更新 `/boot/extlinux/extlinux.conf` 的 `default` 项为 `flange-recovery` 并重启。recovery 启动后，`recoveryctl reboot normal` 将默认项恢复为 `flange` 后重启。

**理由**: 该方案不要求首版改 U-Boot 环境布局，也不要求新增 Android 风格 misc 分区；当前 rootfs 已挂载 boot 分区，recovery 也可以挂载同一个 boot 分区恢复默认项。

**替代方案**:
- U-Boot env `fw_setenv`: 更像 bootonce，但不同板的 env offset 与冗余布局不统一。
- Android misc 分区: 语义清晰，但需要 bootloader 侧读取 bootloader_message。
- 仅手动 U-Boot 菜单: 实现简单，但 `flange recovery enter` 无法自动进入。

### 决策 4: 首版 transport 使用 ADB over USB

宿主机 `flange recovery` 不直接操作块设备，而是通过 `adb push`、`adb pull`、`adb shell` 调用 recovery 内的 `recoveryctl`。

```text
flange recovery list
└── adb shell recoveryctl list --json

flange recovery flash rootfs rootfs.img
├── adb push rootfs.img /tmp/flange-upload/rootfs.img
└── adb shell recoveryctl flash rootfs /tmp/flange-upload/rootfs.img --sha256 <hash>

flange recovery backup rootfs rootfs-backup.img.zst
├── adb shell recoveryctl backup rootfs /tmp/flange-backup/rootfs.img.zst
└── adb pull /tmp/flange-backup/rootfs.img.zst rootfs-backup.img.zst
```

**理由**: 项目已有 `adbd` 和 USB gadget 能力，ADB 同时提供命令执行、文件传输、等待设备和 shell，非常适合快速闭环。

**替代方案**:
- USB DFU: 适合下载镜像，但备份和复杂分区查询不方便。
- 自定义 USB 协议: 可控性更高，但需要 host/device 两端协议栈，首版成本高。

### 决策 5: `recoveryctl` 承接设备端真实操作

`recoveryctl` 是设备端 CLI，不做常驻 daemon。它读取 `/etc/flange/recovery-config.json`，结合 `/dev/disk/by-partlabel`、`lsblk --json`、`blkid`、`findmnt --json` 和 `/proc/cmdline` 获取真实设备状态。

`recoveryctl` 提供：

- `mode`
- `list --json`
- `flash <partition> <image> --sha256 <hash> [--force]`
- `backup <partition> <output> [--compress zstd|none]`
- `reboot normal|recovery`

**理由**: ADB 已提供进程启动和传输能力，首版不需要维护常驻服务、认证和 socket 生命周期。

**替代方案**: 做一个 `recoveryd` 常驻服务。优点是适合未来自定义协议；缺点是首版复杂度更高。

### 决策 6: 分区写入默认保护

`recovery-config.json` 标记每个分区的操作策略：

- `bootloader`/`raw` 类分区默认 `protected: true`
- `recovery` 分区默认禁止写入
- `boot`、`rootfs`、`userdata` 可按策略允许备份或刷写

刷写前必须检查目标分区存在、镜像大小不超过分区大小、目标分区未挂载、sha256 匹配。写入后执行 `sync`，并按能力做读回校验。

**理由**: recovery 具备整盘写权限，必须把最容易造成设备不可启动的操作显式挡住。

## Risks / Trade-offs

- [分区布局变更导致首次部署必须全量刷写] -> 在 proposal 和任务中明确这是一次分区表变更；实机验证必须从整盘镜像开始。
- [extlinux 默认项修改过程中断电] -> 使用临时文件加原子 rename；最坏情况停留在 recovery，`recoveryctl reboot normal` 可恢复默认项。
- [ADB 未枚举导致无法线刷] -> 保留串口/U-Boot 手动进入 recovery 的路径；`flange recovery enter` 和 `flange recovery list` 必须给出 USB gadget 排查提示。
- [不同平台 boot 分区布局不同] -> 将 normal/recovery label 生成放在平台 boot builder 中，公共约束写入 spec，不在 engine 中写平台分支。
- [刷错分区] -> host CLI 和 `recoveryctl` 都使用分区名，不接受裸 block device 作为普通入口；raw/protected 分区需要显式 `--force`。

## Migration Plan

1. 添加 OpenSpec specs 和任务，确认能力边界。
2. 先实现 Rockchip 平台 recovery 分区、recovery 构建和 extlinux 双入口。
3. 接入 `flash-config.json` 和 `recovery-config.json` 生成，确保整盘镜像包含 recovery。
4. 实现 `recoveryctl list`，先完成只读分区识别闭环。
5. 实现 `flange recovery list/shell/reboot`，验证 ADB 线刷通道。
6. 实现 `backup`，再实现 `flash rootfs`，最后评估 boot/userdata 允许策略。
7. 实机验证：整盘刷写、normal 启动、进入 recovery、列分区、备份 rootfs、刷写 rootfs、回 normal。

回滚策略：若 recovery 分区布局或启动入口导致设备不能正常启动，使用现有宿主机 `flange flash` 全量刷回不含 recovery 的旧镜像。

## Open Questions

- 首版是否只要求 Rockchip 实机验收，还是同时要求 Allwinner A733 生成镜像通过静态验证。
- recovery 分区默认大小需要定为多少；完整 Ubuntu 小系统建议先按 256MB 到 512MB 预留，再根据实际包集合压缩。
- `recoveryctl` 作为 `components/app/recoveryctl` 打包，还是放入 `components/packages/` 作为更底层的系统包。
