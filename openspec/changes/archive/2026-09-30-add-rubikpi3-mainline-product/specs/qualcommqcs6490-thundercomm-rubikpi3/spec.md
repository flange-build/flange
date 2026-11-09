## MODIFIED Requirements

### Requirement: RUBIK Pi 3 板级目标

系统 MUST 提供 `thundercomm-rubikpi3` 板级配置，绑定 `platform=qualcommqcs6490`、`soc=qcs6490`，
products 为 `default`、`desktop`、`mainline`，variants 为 `debug`、`release`。GRUB 启动与 LUN0 分区几何 MUST 继承
SoC 层；`default` 与 `desktop` 的内核 MUST 由板级覆盖为厂商内核（见「厂商内核基线」），`mainline` 的内核 MUST 继承
SoC 层（见「mainline product」）；设备树 MUST 为 `qcom/qcs6490-thundercomm-rubikpi3`。`desktop` MUST 且仅有
`desktop` 启用 `ubuntu-desktop` 硬件特性包。

#### Scenario: 六个目标均通过严格校验

- **WHEN** 求值 `thundercomm-rubikpi3-{default,desktop,mainline}-{debug,release}`
- **THEN** canonical 校验通过，DTB 名为 `qcs6490-thundercomm-rubikpi3`；kernel source 在 `default` / `desktop` 为
  `rubikpi-linux`，在 `mainline` 为 `linux-qcs6490`

#### Scenario: product 决定桌面

- **WHEN** 求值 `desktop` 与 `default` / `mainline`
- **THEN** 仅 `desktop` 的 custom packages 含 `flange-ubuntu-desktop-config`，rootfs 镜像为 4G

#### Scenario: 不再提供 el1 product

- **WHEN** 求值 `thundercomm-rubikpi3-el1-release`
- **THEN** 目标解析失败，提示该板没有 `el1` product

### Requirement: 板载无线与 USB3 固件

`default` 与 `desktop` 的 rootfs MUST 按 bcmdhd 的查找路径安装 AP6256 固件：`/lib/firmware/fw_bcm43456c5_ag.bin`、
`/lib/firmware/nvram.txt` 与 `/lib/firmware/config.txt`，以及蓝牙用的 `brcm/BCM4345C5.hcd`，均取自
`rubikpi-ai/rubikpi3-firmware`，MUST NOT 安装 brcmfmac 专用的 `brcmfmac43456-sdio.*` 文件。`mainline` 的 rootfs
MUST 按 brcmfmac 的查找路径安装同源同版本的 `brcm/brcmfmac43456-sdio.{bin,clm_blob}`（取自 `radxa-firmware`）、
由 `rubikpi3-firmware` 的 `nvram.txt` 改名的 `brcm/brcmfmac43456-sdio.thundercomm,rubikpi3.txt` 与
`brcm/BCM4345C5.hcd`。所有 product MUST 安装 `bluez`。系统 MUST 在 sysinit 阶段只读挂载 `usb_fw` 分区到
`/var/usbfw`，使 `/usr/lib/firmware/renesas_usb_fw.mem` 可解析，并重新探测未绑定的 Renesas xHCI；
分区或固件缺失时 MUST 仅记录并继续启动。

#### Scenario: bcmdhd 固件布局

- **WHEN** 求值 `default` 或 `desktop` 目标
- **THEN** `rootfs.extra_firmware` 含来自 `rubikpi3-firmware` 的 `fw_bcm43456c5_ag.bin`、`nvram.txt`、
  `config.txt`、`brcm/BCM4345C5.hcd`，且不声明 `radxa-firmware` 源

#### Scenario: brcmfmac 固件布局

- **WHEN** 求值 `mainline` 目标
- **THEN** `rootfs.extra_firmware` 含来自 `radxa-firmware` 的 `brcm/brcmfmac43456-sdio.{bin,clm_blob}` 与来自
  `rubikpi3-firmware` 的改名 NVRAM、`brcm/BCM4345C5.hcd`，不含 bcmdhd 的 `fw_bcm43456c5_ag.bin`

#### Scenario: Wi-Fi 上电并扫描

- **WHEN** 刷写 `default` 后启动并 `ip link set wlan0 up`
- **THEN** dhd 加载固件与板级 NVRAM 成功，`iw dev wlan0 scan` 能扫到 2.4 GHz 与 5 GHz 热点

#### Scenario: 缺少 usb_fw 不阻塞启动

- **WHEN** 设备没有 `usb_fw` 分区或其中没有固件
- **THEN** 服务成功退出并记录跳过原因，系统继续启动

### Requirement: 厂商内核基线

`default` 与 `desktop` 的内核源 MUST 为 `https://github.com/rubikpi-ai/linux.git`，钉住 commit
`a579877ac6b4afc6df09d8e53564dfb08d9d693f`（Thundercomm Yocto QLI 1.5 参考构建所用版本）。
`kernel.defconfig` MUST 依次为 `qcom_defconfig`、`qcom_addons.config`、`rubikpi3.config`，SoC 层
`kernel.config` 覆盖 MUST 继续在其后生效；构建后的 `.config` 中 UFS 主控、QMP UFS PHY 与 USB gadget
configfs MUST 为 builtin。平台层与板级针对 mainline 的 kernel 补丁 MUST 通过 `kernel.exclude_patches` 全部排除。

#### Scenario: 配置指向厂商内核

- **WHEN** 求值 `default` 或 `desktop` 目标
- **THEN** `sources.rubikpi-linux.commit` 为 `a579877ac6b4afc6df09d8e53564dfb08d9d693f`，defconfig 链为
  `qcom_defconfig`、`qcom_addons.config`、`rubikpi3.config`，平台层与板级 kernel 补丁全部位于 `exclude_patches`

#### Scenario: 内核构建成功

- **WHEN** 为 `default` 构建 kernel 组件
- **THEN** 不应用任何平台层或板级补丁，产出 6.6.90 的 `Image` 与 `qcs6490-thundercomm-rubikpi3.dtb`，
  `.config` 中 `CONFIG_SCSI_UFS_QCOM=y`、`CONFIG_PHY_QCOM_QMP_UFS=y`、`CONFIG_USB_CONFIGFS=y`

### Requirement: Yocto 同款 DTB 组合

`default` 与 `desktop` 的 base DTB MUST 由厂商内核树编译并带 `__symbols__`，构建期 MUST 合并板级
`rubikpi3-video.dtbo`：`&venus` 的 `compatible` 为 `qcom,qcm6490-iris-vpu`，含 `non-secure-cb` 子节点
（`compatible = "qcom,vidc,cb-ns"`，`iommus = <&apps_smmu 0x2180 0x20>`）。系统 MUST NOT 合并把 GPU
改为 KGSL 的 graphics overlay、camera overlay 或 `rubikpi3-overlay.dtbo`。rootfs `/boot` 与 `dtb.bin` 中的
DTB MUST 相同。

#### Scenario: 合并结果

- **WHEN** 为 `default` 构建 boot 组件
- **THEN** 最终 DTB 的 venus 节点 compatible 为 `qcom,qcm6490-iris-vpu`，GPU 节点 compatible 不含
  `qcom,kgsl`，且 `/boot` 中的 DTB 与 `dtb.bin` 内 `combined-dtb.dtb` 字节一致

### Requirement: EL1 下 DSP 与硬件编码同时可用

`default` 与 `desktop` MUST 刷写固件包默认（Gunyah）`xbl_config`，MUST NOT 声明 `ufs_file_overrides`，
Linux 运行在 EL1。内核 MUST 以 out-of-tree 模块提供 CodeLinaro `video-driver`
（`video.qclinux.1.0.r1-rel` @ `80f2b25ae580d0cd8cf30ac5e299d7d526e3e995`）编译的 `iris_vpu.ko`，
加载 `qcom/vpu-2.0/vpu20_1v.mbn`。ADSP 与 CDSP MUST 由内核经 PAS 加载并进入 running。

#### Scenario: 配置为 EL1

- **WHEN** 求值 `default` 或 `desktop` 目标
- **THEN** `bootloader` 不含 `ufs_file_overrides`，`kernel.oot_modules` 含产出 `iris_vpu.ko` 的条目

#### Scenario: 硬件编码不复位

- **WHEN** 刷写 `default` 后启动并对 720p NV12 执行 H.264 硬件编码
- **THEN** 无 `/dev/kvm`，`iris_vpu` 已加载，输出有效 H.264 码流且设备不复位

#### Scenario: DSP 可用

- **WHEN** 刷写 `default` 后启动
- **THEN** ADSP 与 CDSP remoteproc 状态为 running，FastRPC `GET_DSP_INFO` 与 `INIT_ATTACH` 在两者上均成功

## ADDED Requirements

### Requirement: mainline product

`mainline` MUST 继承 SoC 层内核（`linux-qcs6490`，radxa `linux-7.0.2`）的 source、defconfig 链与平台层补丁，
MUST NOT 声明 `kernel.exclude_patches`、`kernel.oot_modules` 或厂商内核源。它 MUST 刷写 KVM 版 `xbl_config`
（`bootloader.ufs_file_overrides` 为 `xbl_config.elf → xbl_config_kvm.elf`），使 Linux 运行在 EL2；base DTB MUST 在
构建期合并 `rubikpi3-el2.dtbo`（禁用 GPU zap shader、ADSP/CDSP 声明 PAS SMMU 流、启用 APSS watchdog、SCM SHM
bridge 归属自身、venus 追加 SMMU 流与 `video-firmware` 子节点），rootfs `/boot` 与 `dtb.bin` 中的 DTB MUST 一致。
本板 TZ 不支持 `PAS_GET_RSCTABLE`，`mainline` 下 ADSP/CDSP 离线是已知限制，MUST 在板页记录。

#### Scenario: 配置为 EL2 mainline

- **WHEN** 求值 `mainline` 目标
- **THEN** kernel source 为 `linux-qcs6490`，无 `exclude_patches` 与 `oot_modules`，`build_overlays` 与
  `boot.overlays.board` 均为 `rubikpi3-el2.dtbo`，`ufs_file_overrides` 为 `xbl_config.elf → xbl_config_kvm.elf`

#### Scenario: EL2 硬件编码可用

- **WHEN** 刷写 `mainline` 后启动并对 720p NV12 执行 H.264 硬件编码
- **THEN** `/dev/kvm` 存在，编码输出有效 H.264 码流且设备不复位

### Requirement: mainline 上游修复 backport

板级 kernel patches MUST backport 上游 LT9611 DSI Port B（含配套的单 Port B 输入驱动补丁）与 USB QMP PHY
供电修复，且 MUST 能干净应用到 SoC 层钉住的内核 commit；它们只作用于 `mainline`，厂商 product MUST 排除。
SoC 层内核升级到已含修复的版本后 MUST 删除对应补丁。

#### Scenario: 补丁应用

- **WHEN** 为 `mainline` 构建 kernel 组件
- **THEN** 平台与板级补丁全部应用成功，DTS 中 `mdss_dsi0_out` 连接 LT9611 `port@1`

#### Scenario: LT9611 以 Port B 探测

- **WHEN** `mainline` 设备启动
- **THEN** LT9611 驱动探测成功，不出现 "failed to get remote node for primary dsi"
