## 1. 提案与基线

- [x] 1.1 固化调研来源、提案、设计与 5 份 delta spec，`openspec validate --strict` 通过（1 小时）
- [x] 1.2 建立 verification.md：记录实板 EEPROM / TNSPEC、分区表、`/proc/cmdline`、`/proc/config.gz`、L4T 包清单，
      以及参考 `flash.xml`、`flashcmd.txt`、`boot.img`、`kernel_bootctrl.bin`、`emmc_bootblob_ver.txt` 的摘要（1 小时）

## 2. 共享框架改动

- [x] 2.1 schema / validate 增加 `bootloader.l4t_bsp` 下载描述符与 `bootloader.tegraflash` 结构，错误给出字段路径，补单测（1.5 小时）
- [x] 2.2 新增 `rootfs.phase2_packages`：rootfs 专属字段（recovery 拒绝）、Phase 2 在外部 deb 之后经 AptCache 安装、
      进入 rootfs 指纹不进入 Phase 1 快照；单测覆盖执行顺序、指纹与空值无副作用（2 小时）
- [x] 2.3 `LabelSpec` 增加可选 `initrd` 并渲染 `initrd` 行，确认现有平台 extlinux 输出不变（0.5 小时）
- [x] 2.4 sshd drop-in 在 `sshd_config` 缺少 `Include` 时于首行插入并纳入校验；单测覆盖已包含（字节一致）与缺失两种基线（1 小时）

## 3. 平台包与配置

- [x] 3.1 平台包骨架：`ARTIFACT_NAMES`、懒加载 `create_builder`、`required_artifacts`、`DTBO_MERGE_AT_BUILD`、
      运行期 overlay 由通用校验按能力拒绝（无需平台 `validation.py`）；平台契约与能力断言测试（1.5 小时）
- [x] 3.2 platform / SoC / board 三层 Jsonnet：18.04 基线、包与 `adbd` 剔除、NVIDIA APT 源、L4T `phase2_packages`、内核源、
      BSP 描述符、tegraflash 事实、APP 分区、default / jetpack 产品；发现测试与 canonical 目标矩阵（2 小时）
- [x] 3.3 `nvidia-jetpack` 功能包 `config.jsonnet`，测试 jetpack 产品启用而 default 不启用（0.5 小时）

## 4. 内核

- [x] 4.1 kernel builder：`tegra_defconfig` + `flange_overrides.config`、`KCFLAGS=-Wno-error`、Image / modules、DTB 唯一匹配发布；单测覆盖匹配为 0 或多个（1.5 小时）
- [x] 4.2 Docker 编译内核，处理 gcc-10.5 编译问题（必要时加平台补丁），核对 release 并与 stock `/proc/config.gz` 对比关键项（2 小时）

## 5. bootloader 与 boot

- [x] 5.1 BSP 安全解包（`data` 过滤器 + 前缀白名单）与 `bootloader/tegraflash/` 发布；恶意成员与摘要不符的单测（1.5 小时）
- [x] 5.2 用 BSP `mkbootimg` 封装 U-Boot `boot.img`，生成 `kernel_bootctrl.bin`，校验配置引用文件存在（1.5 小时）
- [x] 5.3 boot 组件：以 flange DTB 构建期合并 DTBO，发布 `boot/kernel-dtb.dtb`（1 小时）
- [x] 5.4 Docker 构建 bootloader / boot，`boot.img` 与 `kernel_bootctrl.bin` 与参考产物逐字节对照（1 小时）

## 6. rootfs

- [x] 6.1 TX2 rootfs 子类：Phase 2 标记文件包裹、`/boot/Image`、extlinux（含 initrd、`${cbootargs}`）、`nv_boot_control.conf`、仅挂 rootfs 的 fstab（1.5 小时）
- [x] 6.2 rootfs golden 测试加入新平台并生成 golden（1 小时）
- [x] 6.3 Docker 构建 18.04 rootfs，排查基线包与 L4T 包 postinst 在 chroot 中的问题（2 小时）
- [x] 6.4 检查产物：os-release、L4T 包版本与排除项、标记文件无残留、modules 与内核 release 一致、sshd Include、
      `nv-l4t-usb-device-mode` 已启用、`/boot/initrd` 存在（1 小时）

## 7. image 刷写包

- [x] 7.1 `flash.xml` 生成：token 替换、APP 尺寸、kernel-dtb 文件名、recovery 分区去文件；用合成模板做单测（1.5 小时）
- [x] 7.2 `system.img`：`resize2fs` 到 APP 尺寸后 `mksparse`；按 flash.sh 格式生成 `emmc_bootblob_ver.txt`；rootfs 超尺寸时失败（1.5 小时）
- [x] 7.3 `manifest.json`（刷写参数、分区、身份期望、SHA256）与 `FlashPlan.generate_flash_config`、受保护分区；image golden 特判（1.5 小时）
- [x] 7.4 Docker 组装完整刷写包，与参考 `flash.xml` / `flashcmd.txt` 对照，把差异逐项记入 verification.md（1 小时）

## 8. 宿主刷写策略

- [x] 8.1 `builder/flash/tegra.py` 注册；preflight（x86_64 Linux、manifest 摘要、记录 target_dir）、sysfs 检测与多设备拒绝（1.5 小时）
- [x] 8.2 临时工作副本；`dump eeprom boardinfo` + `chkbdinfo` 解析，与身份期望比对（1.5 小时）
- [x] 8.3 全量刷写、按分区 `signwrite` / `write`、受保护分区、拒绝 offset 写与 `--raw`；命令编排与拒绝路径单测（2 小时）

## 9. 回归与文档

- [x] 9.1 全量 pytest 与 OpenSpec 严格校验，确认其他平台的 golden 与 canonical 结果不变（1 小时）
- [x] 9.2 板卡文档（进入 Recovery、J21 串口接线、刷写与恢复 stock L4T）、README 支持矩阵、ProjectSpec §2.2 平台表、wiki 平台页（1.5 小时）

## 10. 实板验收与归档

- [ ] 10.1 首次全量刷写：记录身份核对输出、刷写日志与串口完整启动日志（1.5 小时）
- [ ] 10.2 启动与连接：串口登录、USB 网络 SSH、以太网 DHCP；`flange flash APP` 与 `flange flash kernel-dtb` 单刷后冷启动（1.5 小时）
- [ ] 10.3 外设：nvgpu 加载与 GPU 频率、Wi-Fi / 蓝牙、USB3 Host、HDMI 控制台、`nvv4l2h264enc` 硬件编码（2 小时）
- [ ] 10.4 构建并刷写 jetpack 产品，运行 CUDA `deviceQuery`、cuDNN 与 TensorRT 样例（2 小时）
- [ ] 10.5 更新 verification.md，全部验收通过后同步主规格、严格校验并归档（0.5 小时）

实板验收未完成的项保持未勾选并在 verification.md 记录实际证据；预计超过两小时的任务须进一步拆分，
不通过缩小范围或伪造完成状态收尾。
