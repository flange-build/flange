## 1. 大小解析与配置校验

- [x] 1.1 新增通用分区大小解析 helper：支持 `M`/`G` 后缀与十六进制 sector，输出 bytes / sectors / MB
- [x] 1.2 为大小解析 helper 添加单元测试：覆盖 `1536M`、`2G`、`0x400000`、非法单位和非 512B 对齐
- [x] 1.3 扩展 `builder/config/validate.py`：校验 `grow_on_first_boot`、`image_size`、rootfs 类型和 rootfs 最后非 raw 分区约束
- [x] 1.4 添加配置校验单元测试：合法 remaining rootfs、rootfs 后有 data 分区、固定 size 小于 image_size、缺失 image_size

## 2. Rootfs 与 Raw 镜像大小应用

- [x] 2.1 修改 Rockchip rootfs 构建器：rootfs.img 优先使用 rootfs entry 的 `image_size`，未声明时保持 4GB 兼容默认
- [x] 2.2 修改 Allwinner A733 rootfs 构建器：与 Rockchip 使用同一大小解析逻辑
- [x] 2.3 修改 Rockchip image 构建器：GPT 初始 rootfs 分区和 raw.img 总大小优先使用 `image_size`
- [x] 2.4 修改 Allwinner A733 image 构建器：GPT 初始 rootfs 分区和 raw.img 总大小优先使用 `image_size`
- [x] 2.5 添加 builder 单元测试：验证 `remaining + image_size` 生成 2GB rootfs.img 和较小 raw.img 布局
- [x] 2.6 添加 rootfs 内容大小保护：rootfs 目录内容加保留余量超过 `image_size` 时构建失败并给出中文错误

## 3. 首次启动扩容 App

- [x] 3.1 新增 `components/app/flange-rootfs-grow/app.yaml`，声明 exec/service 元数据、运行期依赖和安装路径
- [x] 3.2 新增 `/usr/sbin/flange-rootfs-grow` 脚本：解析 root 设备、父磁盘和分区号，兼容 mmcblk 与 sd/nvme 命名
- [x] 3.3 在扩容脚本中实现 `sgdisk -e`、`growpart`、`partx -u`/`partprobe`、`resize2fs` 命令序列和错误处理
- [x] 3.4 新增 `flange-rootfs-grow.service`：systemd oneshot，成功后写入 `/var/lib/flange/rootfs-grown` marker
- [x] 3.5 添加脚本单元测试或命令序列测试：覆盖 root 设备解析、已存在 marker、扩容失败不写 marker、成功写 marker

## 4. 平台配置接入

- [x] 4.1 在 RK3566 rootfs 分区配置中加入 `image_size: "2G"` 与 `grow_on_first_boot: True`
- [x] 4.2 在 Allwinner A733 rootfs 分区配置中加入 `image_size: "2G"` 与 `grow_on_first_boot: True`
- [x] 4.3 将 `flange-rootfs-grow` 加入启用首次启动扩容目标的 `rootfs.custom_packages`
- [x] 4.4 确认 normal rootfs 包集合包含扩容脚本所需依赖：`cloud-guest-utils`、`gdisk`、`e2fsprogs`、`util-linux`

## 5. 文档与验证

- [x] 5.1 更新 README 或相关文档：说明 `image_size`、`grow_on_first_boot` 和首次启动扩容行为
- [x] 5.2 运行 OpenSpec 校验，确保 proposal/design/specs/tasks 状态完整
- [x] 5.3 运行相关 Python 单元测试：配置校验、大小解析、rootfs/image 构建器、App 打包
- [x] 5.4 在可用 Docker 环境中执行一次目标 rootfs/image 构建，确认 `rootfs.img` 与 `raw.img` 小于旧 4GB/4.6GB 产物
