## 1. 配置与分区模型

- [x] 1.1 为 FINAL_CONFIG 增加 `recovery.enabled`、`recovery.packages`、`recovery.custom_packages`、`recovery.transport`、`recovery.protected_partitions` 等字段约定
- [x] 1.2 在配置校验中增加 recovery 启用时的 `recovery` 分区存在性检查
- [x] 1.3 为 Rockchip RK3566 默认分区表加入 `recovery` 分区并调整后续分区 offset
- [x] 1.4 为 Allwinner A733 分区表加入 `recovery` 分区或明确首版仅静态预留配置
- [x] 1.5 编写配置解析测试：启用 recovery 但缺少 `recovery` 分区时报错
- [x] 1.6 编写分区布局测试：启用 recovery 的 target 可解析出 recovery 分区 offset、size、type

## 2. 构建图与缓存

- [x] 2.1 在 `builder/cache.py` 的 `DEPENDENCY_GRAPH` 中加入 `recovery: ["app", "kernel"]`
- [x] 2.2 在 `REQUIRED_ARTIFACTS` 中加入 `recovery/recovery.img` 校验
- [x] 2.3 扩展内容哈希逻辑，使 `recovery` 哈希包含 recovery 配置、kernel/app 上游哈希、overlay 和分区大小
- [x] 2.4 修改 `builder/engine.py`，支持 `flange build recovery` 调度和产物收集
- [x] 2.5 编写构建图测试：`image` 构建顺序包含 `recovery` 且位于 `image` 之前
- [x] 2.6 编写缓存测试：kernel 或 recovery App 变化会触发 recovery 重建

## 3. Recovery 镜像构建

- [ ] 3.1 新增公共 recovery 构建基类或复用 RootfsBuilder 的 recovery 构建辅助函数
- [ ] 3.2 新增 Rockchip recovery 构建策略，产出 ext4 `recovery.img`
- [ ] 3.3 确保 `recovery.img` 文件系统 label 为 `recovery`
- [ ] 3.4 将 kernel modules 安装进 recovery rootfs
- [ ] 3.5 将 `adbd` 和 `recoveryctl` 安装进 recovery rootfs
- [ ] 3.6 安装 recovery 所需基础工具：`python3-minimal`、`util-linux`、`e2fsprogs`、`parted`、`gptfdisk`、`zstd` 等
- [ ] 3.7 生成并嵌入 `/etc/flange/recovery-config.json`
- [ ] 3.8 编写 recovery 构建测试：产物存在、label 正确、关键文件存在

## 4. Boot 启动入口

- [ ] 4.1 扩展 Rockchip boot builder，启用 recovery 时生成 normal 和 recovery 两个 extlinux label
- [ ] 4.2 扩展 Allwinner A733 boot builder 的 extlinux 生成逻辑或增加待实现保护错误
- [ ] 4.3 实现设备端 boot 默认项切换 helper，支持原子修改 `/boot/extlinux/extlinux.conf`
- [ ] 4.4 确保 recovery 启动后可恢复 normal 默认项
- [ ] 4.5 编写 extlinux 内容测试：包含 normal/recovery label 且 recovery root 指向 recovery 分区
- [ ] 4.6 编写 boot 默认项切换测试：normal -> recovery -> normal 可往返

## 5. Image 与 flash-config 集成

- [ ] 5.1 扩展 Rockchip image builder 的分区镜像映射，写入 `recovery/recovery.img`
- [ ] 5.2 扩展 Allwinner A733 image builder 的分区镜像映射或首版静态跳过策略
- [ ] 5.3 扩展 `RockchipFlashStrategy.partition_image_map()`，加入 `recovery`
- [ ] 5.4 扩展 `AllwinnerA733FlashStrategy.partition_image_map()`，加入 `recovery` 或明确首版不刷写
- [ ] 5.5 扩展 `FlashConfigGenerator`，为 `recovery` 写入 protection 策略元数据
- [ ] 5.6 编写 image 组装测试：raw.img 写入 recovery 分区
- [ ] 5.7 编写 flash-config 测试：包含 recovery 分区和镜像路径

## 6. recoveryctl 设备端工具

- [ ] 6.1 新增 `components/app/recoveryctl/` 或 `components/packages/recoveryctl/` 工程结构
- [ ] 6.2 实现 `recoveryctl mode`，根据 `/proc/cmdline` 或 recovery-config 判断当前模式
- [ ] 6.3 实现 `recoveryctl list --json`，合并 recovery-config 与实际块设备状态
- [ ] 6.4 实现分区名到 block device 的解析，优先使用 `/dev/disk/by-partlabel`
- [ ] 6.5 实现 mounted/mountpoint 检测，基于 `findmnt` 或 `/proc/self/mountinfo`
- [ ] 6.6 实现 `recoveryctl flash` 的 size、sha256、mounted 和 protected 校验
- [ ] 6.7 实现 `recoveryctl flash` 写入与 `sync`，并加入基础读回校验
- [ ] 6.8 实现 `recoveryctl backup`，支持 zstd 压缩和未压缩输出
- [ ] 6.9 实现 `recoveryctl reboot normal|recovery`
- [ ] 6.10 编写 recoveryctl 单元测试：list、flash 校验失败、protected 拒绝、backup 未知分区

## 7. 宿主机 recovery CLI

- [ ] 7.1 新增宿主机 `builder/recovery.py` 或等价模块，定义 `flange recovery` CLI 入口
- [ ] 7.2 实现 ADB transport 抽象：wait、push、pull、shell、interactive_shell
- [ ] 7.3 实现 `flange recovery enter`
- [ ] 7.4 实现 `flange recovery list`，解析 `recoveryctl list --json` 并格式化输出
- [ ] 7.5 实现 `flange recovery flash <partition> <image>`，上传镜像并传递 sha256
- [ ] 7.6 实现 `flange recovery backup <partition> <output>`，拉取备份结果
- [ ] 7.7 实现 `flange recovery shell`
- [ ] 7.8 实现 `flange recovery reboot [normal|recovery]`
- [ ] 7.9 更新 `envsetup.sh` 帮助文本和命令路由
- [ ] 7.10 编写 CLI 单元测试：参数解析、ADB 缺失、normal 模式拒绝 flash、list 格式化

## 8. 安全与错误处理

- [ ] 8.1 为 protected 分区定义默认策略：bootloader/raw/recovery 默认受保护
- [ ] 8.2 为 `--force` 增加 host 侧确认与 device 侧二次校验
- [ ] 8.3 为 ADB 未连接、设备未在 recovery、镜像不存在、分区不存在提供中文错误信息
- [ ] 8.4 确保 `flange recovery` 不接受裸 block device 作为普通分区参数
- [ ] 8.5 编写错误路径测试：ADB timeout、sha256 不匹配、镜像过大、目标已挂载

## 9. 文档与验收

- [ ] 9.1 更新 README 或 docs，说明 recovery 分区、构建命令和 `flange recovery` 用法
- [ ] 9.2 更新 ProjectSpec 或相关设计文档中关于 USB 线刷 recovery 的约定
- [ ] 9.3 添加开发者排障文档：ADB 不识别、USB gadget 未启动、boot 默认项恢复
- [ ] 9.4 运行单元测试：配置、构建图、boot、image、flash-config、recoveryctl、CLI
- [ ] 9.5 本地构建验证：`flange build recovery`
- [ ] 9.6 本地整盘构建验证：`flange build`
- [ ] 9.7 实机验证：全量刷写后 normal 系统启动成功
- [ ] 9.8 实机验证：`flange recovery enter` 进入 recovery
- [ ] 9.9 实机验证：`flange recovery list` 列出真实分区状态
- [ ] 9.10 实机验证：`flange recovery backup rootfs rootfs-backup.img.zst` 成功生成备份
- [ ] 9.11 实机验证：`flange recovery flash rootfs rootfs.img` 成功刷写 rootfs
- [ ] 9.12 实机验证：`flange recovery reboot` 返回 normal 系统
