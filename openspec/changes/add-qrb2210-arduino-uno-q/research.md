# UNO Q 调研与实现对应表

基线日期：2026-09-07。调研按 boot/flash、kernel/drivers、rootfs/firmware/Arduino runtime 三路进行，
集成后交叉审查。固定源码和下载摘要见本变更 design、板级配置及运行时资源锁。

## 硬件与启动职责

| 部分 | 已核验的接口 | flange 落点 |
| --- | --- | --- |
| Linux MPU（主处理器） | Qualcomm QRB2210，板卡身份 `arduino,imola` | `qualcommqrb2210` 平台及共享 UNO Q board |
| MCU（微控制器） | STM32U585，`arduino:zephyr:unoq` | 固定 Zephyr core、上传工具和 Bridge 库 |
| Qualcomm 前级启动 | 官方签名固件及 Firehose 加载器 | 摘要校验后的官方救援包；不自行重建签名固件 |
| `boot_a/boot_b` | Android v0 容器内的 gzip(U-Boot 无 DTB 二进制) + DTB | 自编 U-Boot，严格固定 v0 头及 4 MiB 分区限制 |
| `efi` | systemd-boot、Image、DTB、initrd | FAT ESP；`boot` 实际依赖 rootfs 的 initrd/EFI 资源 |
| 系统与用户数据 | ext4 rootfs；独立 userdata 挂载 `/home/arduino` | 两种存储容量共用镜像，写入前按设备 GPT 校验 |
| MCU 通信 | Router 使用 UART `/dev/ttyHS1`，Bridge 提供 MessagePack RPC | GPIO 控制、Router 服务和固定 Bridge 库；不是 Linux remoteproc 通道 |
| 刷写 | 主机 QDL、USB EDL、eMMC | 独立具名分区策略，保留官方校准/持久化分区 |

## Kernel、driver 与 firmware

以下配置值来自已经实际生成的 debug `.config`。配置存在只能证明编译选择，不能证明实板功能通过。

| 功能 | 实际配置/驱动 | 配套资源与验证要求 |
| --- | --- | --- |
| eMMC | `CONFIG_MMC_SDHCI_MSM=y` | 保持官方完整 GPT，核对实际末尾的备份 GPT |
| Wi-Fi | `CONFIG_ATH10K_SNOC=m`，WCN3990 | Qualcomm WLAN 固件及正确 PCB revision 的 BDF；延后驱动加载至校准完成 |
| Bluetooth | `CONFIG_BT_HCIUART_QCA=y` | QCA 固件、BlueZ，设备节点与连接能力待上板验证 |
| GPU | `CONFIG_DRM_MSM=m` | A702 SQE/ZAP 固件和 Ubuntu Mesa |
| DSP/协处理器 | `CONFIG_QCOM_Q6V5_PAS=m`、`CONFIG_RPMSG_QCOM_GLINK_SMEM=m` | qcm2290 firmware、rmtfs、tqftpserv，不能与独立 Arduino MCU 混为一谈 |
| Qualcomm IPC（处理器间通信） | `CONFIG_QRTR=m`、`CONFIG_QCOM_RMTFS_MEM=m` | Ubuntu 原生 rmtfs/tqftpserv 服务 |
| USB | `CONFIG_USB_DWC3=y`、`CONFIG_PHY_QCOM_QUSB2=m` | Host/设备模式、ADB 与实际供电组合分别验收 |
| 音频 | `CONFIG_SND_SOC_QDSP6=m` | 官方 UCM、DSP 固件及 PipeWire；实际输入输出待验收 |
| 视频 | `CONFIG_VIDEO_QCOM_VENUS=m` | 固件与用户态配套；摄像头按具体传感器/配件另行验证 |
| 设备树 | base + `video_sound-usbc` overlay 合成最终 Imola DTB | 不以 base DTB 代替最终板级 DTB；载板/屏幕 overlay 不是默认全部启用 |

## Ubuntu 与 Arduino 生态的适配结论

- 官方系统采用 Debian trixie；flange 保留 Ubuntu-base。上游 DEB 只提取固定白名单资源，
  系统库由 Ubuntu 提供，不安装绑定官方 kernel 的 `arduino-unoq` 元包。
- 上游 OpenOCD 需要 libgpiod 2.x 的 `libgpiod.so.3`。固定 2.2.2 源码构建到私有目录；
  Router GPIO 命令兼容 Ubuntu libgpiod 1.x，避免用错误的 CLI 参数控制 MCU。
- 启动成功标记对齐 qbootctl 0.2.2 源码。U-Boot 透传唯一合法槽位，用户态明确校验后标记，
  不使用缺少槽位时默认 A 槽的行为。
- App CLI 0.13.0、App Lab 0.10.0、Router 0.10.0、Arduino CLI 1.5.1 与 Zephyr core 0.90.0
  按真实发布索引固定。最终兼容性以目标 Ubuntu 的 `ldd -r` 和实际 sketch 编译结果为准。
- 五份 ARM64 Bricks OCI 镜像固定 manifest/config 摘要，并预装本地归档；EI runner 中 10 个模型已实际提取验证。
  两个可选 GGUF 模型固定下载版本但不预置；其 LFS 摘要为来源审计记录，下载器未新增字节摘要门禁。
- 用户数据保留不等于生态资源自动升级。系统记录期望资源锁，更新后的 rootfs 若遇旧 userdata 锁不匹配，
  必须明确诊断并迁移，不能静默继续或覆盖用户 sketch。

## 主要来源

- [Arduino Linux kernel](https://github.com/arduino/linux-qcom)、[Arduino U-Boot](https://github.com/arduino/u-boot)。
- [Arduino 官方镜像配方](https://github.com/arduino/arduino-deb-images)、[官方刷写工具](https://github.com/arduino/arduino-flasher-cli)。
- [Arduino APT 索引](https://apt-repo.arduino.cc/dists/stable/main/binary-arm64/Packages)。
- [Arduino Zephyr core](https://github.com/arduino/ArduinoCore-zephyr)、[Router](https://github.com/arduino/arduino-router)、[remoteocd](https://github.com/arduino/remoteocd)。
- [App CLI](https://github.com/arduino/arduino-app-cli)、[App Lab](https://github.com/arduino/arduino-app-lab)、[Bricks](https://github.com/arduino/app-bricks-py)。
- [QDL v2.4](https://github.com/linux-msm/qdl/tree/v2.4)、[AOSP mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg/)。

实际通过、失败和未执行项单列于 [verification.md](verification.md)；本表不是硬件认证声明。
