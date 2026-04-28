## Context

当前 Rockchip 与 Allwinner A733 的 rootfs/image 构建策略都把 `size: "remaining"` 固定解析为 4GB：
rootfs 构建器据此生成 4GB `rootfs.img`，image 构建器据此生成约 4.6GB 的 `raw.img`。这让“设备最终想占满
剩余空间”的分区语义直接泄漏到“构建机需要生成多大的文件”，导致构建产物过大。

启动侧已经具备可行基础：normal 启动通过 `PARTLABEL=rootfs` 或固定 `PARTUUID` 定位分区，不依赖 ext4 文件系统
本身的大小。只要 raw 镜像中的初始 GPT 分区可启动，normal 系统进入 userspace 后即可扩展分区和 ext4 文件系统。

## Goals / Non-Goals

**Goals:**

- 让 `rootfs.img` 与 `raw.img` 的初始大小可配置，默认可从 4GB 降到 1.5GB 或 2GB。
- 保留 `size: "remaining"` 表达“设备最终占用剩余空间”的语义。
- 在 normal 系统首次启动时自动扩展 rootfs 分区和 ext4 文件系统。
- 让 Rockchip 与 Allwinner A733 共用相同的大小解析规则，避免平台策略分叉。
- 在配置解析阶段尽早拒绝不安全布局。

**Non-Goals:**

- 不实现 OTA、A/B rootfs、运行时迁移其它分区或 data 分区自动搬移。
- 不改变 recovery 分区的构建流程。
- 不要求宿主机安装分区或 ext4 工具。
- 不改变已有固定 size 分区在未声明 `image_size` 时的行为。

## Decisions

### 决策 1: 在分区 entry 上声明初始镜像大小

新增字段：

```python
{"name": "rootfs", "offset": "0x128000", "size": "remaining",
 "type": "ext4", "image_size": "2G", "grow_on_first_boot": True}
```

- `size`：最终设备分区语义，`remaining` 仍表示运行后扩展到磁盘末尾。
- `image_size`：构建产物中的初始文件系统大小和 raw.img 内初始 GPT rootfs 分区大小。
- `grow_on_first_boot`：启用 normal 系统首次启动扩容。

`image_size` 支持 `M`/`G` 后缀，内部转换为 512B sector；十六进制字符串仍按 sector 解释，与现有 `size` 一致。

替代方案是放到 `rootfs.image_size_mb`。分区 entry 更好，因为大小语义和分区布局绑定，也便于未来对其它 ext4 分区复用。

### 决策 2: 构建大小解析集中到通用 helper

新增通用大小解析 helper，供 Rockchip 与 Allwinner A733 rootfs/image 构建器共用：

- rootfs 生成 `rootfs.img` 时使用 rootfs entry 的 `image_size`。
- raw image 创建 GPT 时，若 entry 有 `image_size`，使用它作为初始 GPT 分区大小。
- 若 entry 无 `image_size` 且 `size == "remaining"`，保持当前兼容行为：默认 4GB。
- 固定 size 分区未声明 `image_size` 时继续使用 `size`。

这样可先以最小兼容方式落地，不会突然改变现有 target 的产物大小。

### 决策 3: 首次启动扩容作为内置 App

新增 `components/app/flange-rootfs-grow/`，打包为普通 deb 并通过 `rootfs.custom_packages` 安装进 normal 系统。
它包含：

- `/usr/sbin/flange-rootfs-grow`：执行扩容动作。
- `/lib/systemd/system/flange-rootfs-grow.service`：`Type=oneshot` 服务。
- `/var/lib/flange/rootfs-grown`：幂等 marker，成功后不再重复执行。

脚本流程：

1. 用 `findmnt -n -o SOURCE /` 找到当前 root 设备。
2. 用 `lsblk -no PKNAME,PARTN` 解析父磁盘和分区号，兼容 `/dev/mmcblk0pN` 与 `/dev/sdXN`。
3. 执行 `sgdisk -e <disk>`，把 GPT backup header 修正到真实磁盘末尾。
4. 执行 `growpart <disk> <partnum>` 扩展 rootfs 分区。
5. 执行 `partx -u <disk>` 或 `partprobe <disk>` 刷新内核分区表。
6. 执行 `resize2fs <rootdev>` 在线扩展 ext4。
7. 写入 marker。

选择 App 而不是直接写 overlay，是因为现有 App 打包机制已经负责文件安装、systemd enable 和依赖声明，和项目的“自定义软件包”
模型一致。

### 决策 4: 配置校验保护可增长布局

启用 `grow_on_first_boot` 的分区必须满足：

- 分区名为 `rootfs`，类型为 `ext4`。
- `image_size` 必须存在且大于 0。
- 若 `size == "remaining"`，该分区必须是最后一个非 raw 分区。
- 若 `size` 是固定值，`image_size` 不得大于固定分区大小。

这样可以避免首次启动时 rootfs 扩展覆盖后续分区，也能在 build 前发现明显错误。

### 决策 5: 依赖放入扩容 App 的 deb control

`flange-rootfs-grow` 声明运行期依赖：

- `cloud-guest-utils`：提供 `growpart`
- `gdisk`：提供 `sgdisk`
- `e2fsprogs`：提供 `resize2fs`
- `util-linux`：提供 `findmnt`、`lsblk`、`partx`

不把这些依赖硬塞进所有平台的 `rootfs.packages`。App 被加入 `rootfs.custom_packages` 后，`dpkg -i` 可能要求依赖已存在；
如当前构建流程不会自动补齐 deb 依赖，则任务中需要同步把这些包加入相关平台的 `rootfs.packages`，保证 chroot 安装成功。

## Risks / Trade-offs

- [GPT backup header 位置不正确] → 首次启动脚本先执行 `sgdisk -e`，再执行 `growpart`。
- [rootfs 不是最后一个可增长分区] → 配置校验直接拒绝。
- [首次启动扩容中途失败] → systemd oneshot 不写 marker，下次启动继续尝试；日志保留在 journal。
- [固定 2GB 初始镜像装不下 debug rootfs] → 构建前用 `du -sm rootfs_dir` 加余量估算，若超过 `image_size` 则报错提示增大配置。
- [在线更新 rootfs 后 marker 已存在] → 新镜像自带空的 `/var/lib/flange/`，不会带入旧系统 marker；分区级刷写后首次启动会重新判断并扩容。

## Migration Plan

1. 先实现字段解析和校验，但未配置 `image_size` 的 target 保持现状。
2. 为 RK3566 与 A733 默认 rootfs entry 加入 `image_size: "2G"` 与 `grow_on_first_boot: True`，并安装扩容 App。
3. 对首次含该能力的整盘镜像，用户仍按现有流程整盘刷写；首次启动后 rootfs 自动扩展。
4. 如现场出现问题，可删除配置中的 `image_size` 和 `grow_on_first_boot` 回退到当前 4GB 产物。

## Open Questions

- 默认初始大小先用 2GB 还是 1536MB？建议首版使用 2GB，给 debug 包和内核模块留余量。
- `flange-rootfs-grow` 是否默认装入所有 platform，还是只在启用 `grow_on_first_boot` 时由配置显式加入？
  建议首版显式加入，避免未启用目标多装运行期工具。
