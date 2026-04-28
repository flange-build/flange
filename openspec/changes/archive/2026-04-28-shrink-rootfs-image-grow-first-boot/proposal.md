## Why

当前 `rootfs` 分区使用 `size: "remaining"` 时，构建器把 rootfs 和整盘 raw 镜像都固定展开到 4GB，导致
`rootfs.img` 约 4GB、`raw.img` 约 4.6GB。多数场景下系统实际内容远小于 4GB，过大的镜像会拖慢构建、传输、
刷写和 recovery 在线更新。

需要把“构建产物的初始大小”和“设备上最终可用 rootfs 容量”解耦：构建小镜像，首次启动后自动扩展到真实磁盘末尾。

## What Changes

- 为 rootfs 分区引入初始镜像大小语义：`partitions.entries[].image_size` 或等价配置用于控制 `rootfs.img` 和
  `raw.img` 内 rootfs 分区的初始大小。
- 保留 `size: "remaining"` 的最终容量语义：刷入设备后 rootfs 仍应扩展到存储介质剩余空间。
- 新增 normal 系统首次启动扩容能力：通过 systemd oneshot 服务修复 GPT backup header、扩展 rootfs 分区并执行
  `resize2fs`。
- 为扩容能力增加配置校验：启用首次启动扩容时，rootfs 必须是最后一个可增长分区，避免覆盖后续分区。
- 同步更新 Rockchip 与 Allwinner A733 的 rootfs/image 构建策略，使两者使用一致的大小解析逻辑。
- 增加针对大小解析、GPT 初始分区大小、首次启动扩容脚本和配置校验的单元测试。

## Non-Goals

- 不实现 A/B rootfs、OTA 更新或在线分区重排。
- 不改变 recovery 分区自身大小策略，也不支持从 recovery 内扩容当前 normal rootfs。
- 不要求宿主机具备 `parted`、`resize2fs` 等工具；构建仍通过 Docker 容器执行。
- 不移除 `size: "remaining"`，也不改变已有固定 size 分区的默认行为。

## Capabilities

### New Capabilities

- `rootfs-auto-grow`: 定义 rootfs 初始镜像大小、整盘 raw 镜像初始布局，以及首次启动自动扩展到真实设备剩余空间的契约。

### Modified Capabilities

- `allwinnera733-platform`: A733 rootfs/image 构建必须遵循新的 rootfs 初始大小与首次启动扩容语义。

## Impact

- 影响代码：
  - `builder/platforms/rockchip/rootfs.py`
  - `builder/platforms/rockchip/image.py`
  - `builder/platforms/allwinnera733/rootfs.py`
  - `builder/platforms/allwinnera733/image.py`
  - `builder/config/validate.py`
  - 新增或复用 `components/app/` 下的首次启动扩容 App
- 影响配置：
  - `components/platform/*/*/config.py` 的 rootfs 分区可声明 `image_size` 与 `grow_on_first_boot`
  - 平台级 `rootfs.packages` 可能需要包含 `cloud-guest-utils`、`gdisk`、`e2fsprogs`、`util-linux`
- 影响产物：
  - `rootfs.img` 和 `raw.img` 默认可显著小于当前 4GB/4.6GB
  - 设备首次启动后 rootfs 分区和 ext4 文件系统会被扩展到磁盘末尾
- 影响测试：
  - 新增大小解析、配置校验、首次启动脚本命令序列和平台 image/rootfs builder 行为测试
