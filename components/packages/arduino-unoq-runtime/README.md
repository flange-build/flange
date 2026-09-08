# UNO Q Ubuntu 运行时

本包在 Docker 内按 `resources.lock.json` 校验资源，提取上游 DEB 内容后由 flange
重新生成 `flange-arduino-unoq-runtime`。不安装上游元包、不执行其维护脚本、不混入
Debian APT 软件源。`prepare.py` 是实际构建入口，缺少资源或校验不通过会失败。

## 固定版本与来源

- Arduino CLI 1.5.1、Router 0.10.0、App CLI 0.13.0、App Lab 0.10.0、radio firmware 0.7.0：
  [Arduino APT 索引](https://apt-repo.arduino.cc/dists/stable/main/binary-arm64/Packages)。
- Zephyr core 0.90.0 及全部 ARM64 工具依赖：
  [Arduino package index](https://downloads.arduino.cc/packages/package_index.json)。
  App CLI 0.13.0 默认 core 约束为 `<1.0.0`，所以没有盲用已经发布的 core 1.0.0。
- Arduino_RouterBridge 0.4.3、Arduino_RPClite 0.3.0：官方 library index。
- Qualcomm/Atheros firmware 20250410-2：Debian non-free-firmware，仅取固件与许可，
  放入 `/usr/lib/firmware/updates`，不安装 Debian 动态库。
- qbootctl 0.2.2：对齐 Debian trixie 的源码版本，在 Ubuntu 内交叉编译，取代 noble 的旧版。
- libgpiod 2.2.2：官方 OpenOCD 需要 `libgpiod.so.3`，源码交叉编译到 `/opt/arduino/lib`，
  并保留 Ubuntu 自带的 `libgpiod.so.2` 与 gpioset 1.x。
- OpenOCD 与 ALSA UCM（音频用例管理）配置：arduino-deb-images 固定提交
  `e7713f1797945296e4ab77dc7040b5d2c32aa047`，每个输入另校验 SHA256。定制 codec 宏
  移入 `Qualcomm/qcm2290/codecs` 并重写 Include，避免覆盖 Ubuntu 的共享 UCM 文件。

资源锁里的版本、URL、摘要都是实查值。后续升级必须整体更新输入并重新完成 ABI、MCU 编译与实板验收。
上游源码、原始 DEB 内的版权说明和固件许可证随内容保留；qbootctl 源码一并装入文档目录。
Qualcomm 二进制 firmware 的许可不等同于 Linux 内核 GPL。

## 用户数据与 MCU

`/home/arduino` 是独立 userdata，UUID 与官方一致。CLI core、工具、库、应用、模型及容器
离线归档保存在此分区。Linux rootfs 单刷不会自动覆盖或更新旧 userdata 中的生态版本。
`load-containers` 比对 rootfs 与 userdata 锁文件，失配时明确拒绝启动 App CLI，不能把旧环境
当成升级成功。升级前需备份整个用户目录，按新包迁移工具及归档，并保留用户 apps/sketch；
当前没有自动跨版本迁移器，不得靠重刷 userdata 处理升级。初始 userdata 为 3 GiB；首启只对
已挂载且 UUID 正确的 ext4 执行 resize2fs，利用现有分区容量，绝不修改 GPT。

不安装上游自动 `burn-bootloader` 首启服务。需要替换 MCU 固件时，用户以 `arduino` 身份显式执行：

```text
/usr/lib/flange/unoq/mcu-initialize --replace-mcu-firmware
```

该命令会替换 MCU 固件及 sketch；成功记录位于 userdata。常规 compile/upload 仍通过
`arduino-cli` 与固定 core 自带的 remoteocd，本地／ADB／SSH 路径分别验收。
Router 0.10.0 官方 main.go 对 Unix socket 显式 chmod 0666，arduino 用户可连接。
Router 使用 `/dev/ttyHS1` 115200；GPIO 设置先验证 `arduino,imola`，兼容 libgpiod 1.x/2.x。

## USB 设备端

独立 `usb/` vendor 组件固定 Arduino adbd 34.0.5-12arduino7，保留 UID1000、bash
与 USB 断连补丁；其 Android 动态库由 Ubuntu APT 提供，已实际通过 `ldd -r`，
没有混入 Debian 系统库。主组件通过 `build.deps` 正式依赖此组件。自有 configfs gadget
使用 VID 2341/PID 0078、FunctionFS UID/GID1000 及 ACM GS0，校验板卡/唯一 UDC，
reset 先解绑并完整清理，支持重复 setup/activate/reset；没有执行过真实硬件枚举。

## Bricks 与模型

`containers.lock.json` 固定 ARM64 manifest 及 config digest：

- `python-apps-base:0.12.0`，与 App CLI 0.13.0 的 RunnerVersion 一致。
- `models-downloader:0.12.0`，提供可选模型下载工具；新下载的外部模型不属于预置模型锁。
- `ei-models-runner:0.12.1`，与 Bricks release/0.12.0 的标准 UNO Q Compose 一致。
- `influxdb:2.7-alpine` 与 `llamacpp-runner:0.12.1`，覆盖其余 UNO Q 适用服务；同样预置。

构建使用 `skopeo` 按 digest 导出 Docker 归档并压缩，首启导入时校验归档 SHA256、
镜像 config digest 和 arm64 架构；以后若内容仍匹配则不重复导入。导入后把实际 Compose
改为本地 `sha256:<configID>`，避免 docker-archive 缺失 RepoDigests 导致再次联网；
此方式已用 Compose `up --pull missing` 的隔离容器验证。
EI runner 的[官方 Dockerfile](https://github.com/arduino/app-bricks-py/blob/release/0.12.0/containers/ei-models-runner/Dockerfile)
明确把 `models/ei-ootb-models/arm64/*` 复制至 `/models/ootb/ei`，这些预置模型随镜像层锁定。
已从实际归档提取 10 个 `.eim` 文件的尺寸和 SHA256，记录于 `models.lock.json`；构建逐项核验并产出 `models.manifest.json`。用户新增的云模型和外部模型需要独立摘要及许可核验。

五种镜像覆盖官方 0.12.0 catalog 中 UNO Q 适用的容器服务，Compose 的 image 实际改写为 digest。
两个可选 GGUF 模型通过原 hf-handler 按需读取固定 Hugging Face commit，URL、尺寸及 LFS SHA256
记录于 `optional-models.lock.json`，构建核验实际 catalog 仍消费这些固定 URL。它们没有预置，
需要网络及约 1.23 GB 额外用户空间；SHA256 是上游 LFS 审计记录，下载器未新增逐字节哈希门禁。
gesture/QNN/genie 的 catalog 限定为 Ventuno Q，不属于 UNO Q。云服务仍需要用户网络和凭据。
所有 Bricks 的完整实板验收仍按 OpenSpec 任务推进。

## 验证与限制

rootfs 构建会核验必需 firmware、WCN3988 的 `apbtfwNN.tlv/apnvNN.bin` 配对、
ARM64 ELF 动态符号依赖，并真正编译一个无外设 sketch。不会执行任何 upload。
生成的 `/usr/share/flange/unoq/abi-report.json` 是构建验证证据，不是实板兼容证明。

板级 BDF 依据 `/dev/mmcblk0boot0p3` 选择新旧 PCB；身份或 revision 缺失会报错。
音频恢复按 `qcom/qcm2290/adsp.mbn` 定位处理器，不依赖 `remoteproc1` 枚举编号。
qbootctl 成功标记必须由前级启动槽位确定：优先读取 U-Boot EFI fixup 写入的
`/chosen/arduino,boot-slot`，命令行若也携带 slot_suffix 必须一致；绝不缺省写 A 槽。

`arduino-linux-config` 的 carrier 功能需要特定 EFI/DTB 路径，当前仅标准 UNO Q 被配置。
任意 Media Carrier 的在线修改 DTB、CSI/DSI 配件并未完成迁移或验收；不能以工具已安装
宣称这些硬件通过。App Lab 的发行版升级功能也不能代替 flange 镜像构建与升级流程。
