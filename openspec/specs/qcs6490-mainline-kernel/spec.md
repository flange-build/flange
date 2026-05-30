# qcs6490-mainline-kernel Specification

## Purpose
定义 qcs6490 SoC 在 mainline `radxa/kernel@linux-6.18.2` 基线上的能力契约：内核基线切换、default 产物启动与 UFS 稳定、硬件视频编解码（venus），以及在该基线上重新验证通过的板载外设默认能力（AIC8800 USB Wi-Fi、adb-over-USB gadget）。
## Requirements
### Requirement: 内核基线切换到 mainline linux-6.18.2

系统 SHALL 将 qcs6490 SoC 的内核源分支配置为 `radxa/kernel.git` 的 `linux-6.18.2`（mainline 6.18 系），并 SHALL 复用现有 `grub-with-dtb` 的 boot/image/EDL 刷写流水线；构建出的内核 Image 与 dtb SHALL 来自该分支。MODULE_SIG_FORCE 等 flange 既有 `disable_configs` 约定 SHALL 在新基线上复核保持一致行为。

#### Scenario: 内核从 linux-6.18.2 构建成功
- **WHEN** 配置 `repos.kernel.branch = linux-6.18.2` 并执行 `flange build kernel`
- **THEN** 成功检出该分支并编出 `Image` 与 `qcs6490-radxa-dragon-q6a` 对应的 dtb，无构建中断

#### Scenario: venus DT 在 mainline 基线带 iommus
- **WHEN** 反查构建出的 dtb 中 `video-codec@aa00000`
- **THEN** 其 `status` 为 `okay` 且保留 `iommus`、`video-decoder`/`video-encoder` 子节点（不被 addons 类节点删除）

### Requirement: default 产物启动与 UFS 稳定

系统 SHALL 保证 `radxa-dragon-q6a-default-*` 在 mainline 基线上能正常启动到 rootfs，且 UFS 链路稳定、不发生 HS-G4 PHY 训练导致的 SoC 复位。

#### Scenario: default 启动到 rootfs
- **WHEN** 刷入 mainline 基线镜像并上电
- **THEN** 串口（ttyMSM0）可见内核启动到 systemd、rootfs 挂载成功、adb/控制台可登录

#### Scenario: UFS 不复位
- **WHEN** 系统启动并访问 UFS 存储
- **THEN** 无 `ufs_qcom` probe 复位 / HS-G4 PHY 训练失败导致的 SoC reset，存储读写正常

### Requirement: 硬件视频编解码可用

系统 SHALL 在 mainline 基线上使 venus 视频编解码 probe 成功并暴露 V4L2 运行时节点。

#### Scenario: venus probe 成功且出现运行时节点
- **WHEN** 系统启动完成
- **THEN** `dmesg` 中 venus 驱动 probe 成功无 fatal 错误，`/dev/video*` 与 `/dev/media*` 出现

#### Scenario: 可枚举编解码能力
- **WHEN** 执行 `v4l2-ctl --list-devices` 与对各节点 `v4l2-ctl -d <node> --all`
- **THEN** 列出解码器/编码器设备并可枚举受支持的 codec 像素格式

#### Scenario: 硬件解码端到端可用
- **WHEN** 安装 GStreamer 并对 8-bit 4:2:0 H.264 流执行 `filesrc ! h264parse ! v4l2h264dec ! fakesink`
- **THEN** 管线跑完到 EOS、`v4l2h264dec` src caps 为 `video/x-raw,format=NV12`，无报错、设备不复位

#### Scenario: 硬件编码当前触发 SoC 复位（已知缺陷）
- **WHEN** 通过 `v4l2h264enc` 发起任意配置的硬件编码 streaming
- **THEN** 设备硬复位、Linux 层无任何日志（firmware/HFI 级故障）；编码器节点 `/dev/video0` 与固件仍声明 H264/HEVC 能力，故判定为运行时缺陷而非能力缺失，定位需 ttyMSM0 串口

### Requirement: 既有功能重验门槛

迁移 SHALL 以"default 启动 + UFS + codec"为首个完成里程碑；BSP 上已验证的功能（魅族 E3 屏、aic8800 wifi、adb 自愈、GPU drm/msm）SHALL 作为后续独立任务在新内核上逐项重新验证，并 SHALL 在文档中记录各项重验状态。

#### Scenario: 里程碑达成判定
- **WHEN** default 启动 + UFS 稳定 + codec 三项均实板通过
- **THEN** 首个里程碑视为达成；屏/wifi/adb/GPU 的重验状态在 wiki 中逐项标注（通过 / 待办 / 回退）

#### Scenario: 任意阶段可回退到 BSP
- **WHEN** 迁移过程中某阶段在 mainline 上无法通过
- **THEN** 将 `repos.kernel.branch` 改回 `kernel.qclinux.1.0.r1-rel` 重建即可恢复已知可用的 BSP 基线

### Requirement: AIC8800 USB Wi-Fi 默认可用

mainline 6.18.2 不带 in-tree aic8800 驱动，系统 SHALL 以 out-of-tree 模块从 `radxa-pkg/aic8800` 编译 `aic_load_fw` 与 `aic8800_fdrv` 并随 rootfs 安装，使板载 AIC8800 D80 USB Wi-Fi 作为 qcs6490 平台默认能力开机即可用。OOT 编译 SHALL 适配该内核版本的 cfg80211 API（`get_tx_power` 新增 `radio_idx`/`link_id` 参数），并 SHALL 串行编译（`MAKEFLAGS= make -j1`）以规避大文件交叉编译在受限容器内的 OOM。固件 SHALL 安装到驱动查找路径 `/lib/firmware/aic8800D80/`。

#### Scenario: 驱动加载且射频工作
- **WHEN** default 产物开机
- **THEN** `lsmod` 含 `aic8800_fdrv`/`aic_load_fw`、出现 `wlx<MAC>` 无线接口，`iw dev <iface> scan` 能扫到周边 AP

### Requirement: adb-over-USB gadget 默认可用

系统 SHALL 使 `radxa-dragon-q6a` 的 `usb_1`(usb@a600000, USB-A SS 口) 在 DT 中以 `dr_mode = "peripheral"` 注册 UDC，并 SHALL 把 USB gadget 组合栈（`USB_LIBCOMPOSITE`/`USB_CONFIGFS`/`USB_F_FS`）编为 builtin，使 adbd 经 configfs/functionfs 在开机时建立 adb gadget。`usb_2`(板载 hub + AIC8800) SHALL 保持 host；改 `usb_1` 数据角色 SHALL NOT 影响经 qmpphy 独立 lane 输出的 HDMI。

#### Scenario: 开机自动上线无需手动干预
- **WHEN** USB 口接到主机并开机
- **THEN** `/sys/class/udc/a600000.usb/state` 为 `configured`，主机 `adb devices` 可见该设备；usbdevice 服务经自愈最终 active（无需手动 restart）

### Requirement: 魅族 E3 屏（meizu-e3-bringup product）在 mainline 重验通过

`radxa-dragon-q6a-meizu-e3-bringup-*` 产物 SHALL 在 mainline 6.18.2 基线上完成魅族 E3 39pin MIPI-DSI 屏的显示 + 触摸 + 背光 bring-up：经 `meizu-e3-panel` 包注入的 `panel_meizu_e3`/`sec_ts`/`sgm37604a` 三个 OOT 驱动 SHALL 能对 mainline 6.18 内核编译通过（适配 `asm/fb.h`/`asm/unaligned.h` 移除、`GPIOF_DIR_IN`→`GPIOF_IN`、`FB_EVENT_BLANK` 移除等 ABI 漂移，并 SHALL 同时保持 rock5b/a7a 旧 BSP 内核可编）。触摸/背光所在 `i2c13` SHALL 去除 base board dts 的 `qcom,enable-gsi-dma`（`patches/kernel/0003`），使 geni i2c 走 FIFO 模式、避免 GPI DMA 传输失败；该改动 SHALL NOT 影响 default 产物。

#### Scenario: 显示 + 触摸 + 背光实板可用
- **WHEN** 刷入 meizu-e3-bringup 产物并上电、屏接到 J10 LCD FPC
- **THEN** `/sys/class/drm/card0-DSI-1` 为 `connected`/`enabled` @ 1080×2160 且面板有画面、`sec_ts` 读到 device id `AC,6F,70` 且手指触摸使其 IRQ(gpio81) 计数累增、`/sys/class/backlight/sgm37604a` 亮度可写且生效

#### Scenario: i2c13 无 GPI DMA 传输失败
- **WHEN** meizu-e3-bringup 产物开机、`sec_ts`/`sgm37604a` 在 `i2c13` 上 probe
- **THEN** `dmesg` 无 `geni_i2c ... GPI transfer failed`，触摸与背光的 i2c 读写均成功

