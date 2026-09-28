## MODIFIED Requirements

### Requirement: RUBIK Pi 3 板级目标

系统 MUST 提供 `thundercomm-rubikpi3` 板级配置，绑定 `platform=qualcommqcs6490`、`soc=qcs6490`，
products 为 `default`、`desktop`，variants 为 `debug`、`release`。GRUB 启动与 LUN0 分区几何 MUST 继承
SoC 层；内核 MUST 由板级覆盖为厂商内核（见「厂商内核基线」）；设备树 MUST 为
`qcom/qcs6490-thundercomm-rubikpi3`。`desktop` MUST 且仅有 `desktop` 启用 `ubuntu-desktop` 硬件特性包。

#### Scenario: 四个目标均通过严格校验

- **WHEN** 求值 `thundercomm-rubikpi3-{default,desktop}-{debug,release}`
- **THEN** canonical 校验通过，kernel source 为 `rubikpi-linux`，DTB 名为 `qcs6490-thundercomm-rubikpi3`

#### Scenario: product 决定桌面

- **WHEN** 求值 `desktop` 与 `default`
- **THEN** 仅 `desktop` 的 custom packages 含 `flange-ubuntu-desktop-config`，rootfs 镜像为 4G

#### Scenario: 不再提供 el1 product

- **WHEN** 求值 `thundercomm-rubikpi3-el1-release`
- **THEN** 目标解析失败，提示该板没有 `el1` product

### Requirement: 板载无线与 USB3 固件

rootfs MUST 按 bcmdhd 的查找路径安装 AP6256 固件：`/lib/firmware/fw_bcm43456c5_ag.bin`、
`/lib/firmware/nvram.txt` 与 `/lib/firmware/config.txt`，以及蓝牙用的 `brcm/BCM4345C5.hcd`，
均取自 `rubikpi-ai/rubikpi3-firmware`；MUST 安装 `bluez`。rootfs MUST NOT 再安装 brcmfmac 专用的
`brcmfmac43456-sdio.*` 文件。系统 MUST 在 sysinit 阶段只读挂载 `usb_fw` 分区到 `/var/usbfw`，使
`/usr/lib/firmware/renesas_usb_fw.mem` 可解析，并重新探测未绑定的 Renesas xHCI；
分区或固件缺失时 MUST 仅记录并继续启动。

#### Scenario: bcmdhd 固件布局

- **WHEN** 求值任一 RUBIK Pi 3 目标
- **THEN** `rootfs.extra_firmware` 含来自 `rubikpi3-firmware` 的 `fw_bcm43456c5_ag.bin`、`nvram.txt`、
  `config.txt`、`brcm/BCM4345C5.hcd`，且不再声明 `radxa-firmware` 源

#### Scenario: Wi-Fi 上电并扫描

- **WHEN** 刷写 `default` 后启动并 `ip link set wlan0 up`
- **THEN** dhd 加载固件与板级 NVRAM 成功，`iw dev wlan0 scan` 能扫到 2.4 GHz 与 5 GHz 热点

#### Scenario: 缺少 usb_fw 不阻塞启动

- **WHEN** 设备没有 `usb_fw` 分区或其中没有固件
- **THEN** 服务成功退出并记录跳过原因，系统继续启动

## ADDED Requirements

### Requirement: 厂商内核基线

RUBIK Pi 3 的内核源 MUST 为 `https://github.com/rubikpi-ai/linux.git`，钉住 commit
`a579877ac6b4afc6df09d8e53564dfb08d9d693f`（Thundercomm Yocto QLI 1.5 参考构建所用版本）。
`kernel.defconfig` MUST 依次为 `qcom_defconfig`、`qcom_addons.config`、`rubikpi3.config`，SoC 层
`kernel.config` 覆盖 MUST 继续在其后生效；构建后的 `.config` 中 UFS 主控、QMP UFS PHY 与 USB gadget
configfs MUST 为 builtin。平台层针对 mainline 的 kernel 补丁 MUST 通过 `kernel.exclude_patches` 全部排除，
板级 MUST NOT 保留针对 mainline 的 backport 补丁。

#### Scenario: 配置指向厂商内核

- **WHEN** 求值任一 RUBIK Pi 3 目标
- **THEN** `sources.rubikpi-linux.commit` 为 `a579877ac6b4afc6df09d8e53564dfb08d9d693f`，defconfig 链为
  `qcom_defconfig`、`qcom_addons.config`、`rubikpi3.config`，平台层 kernel 补丁全部位于 `exclude_patches`

#### Scenario: 内核构建成功

- **WHEN** 构建 kernel 组件
- **THEN** 不应用任何平台层补丁，产出 6.6.90 的 `Image` 与 `qcs6490-thundercomm-rubikpi3.dtb`，
  `.config` 中 `CONFIG_SCSI_UFS_QCOM=y`、`CONFIG_PHY_QCOM_QMP_UFS=y`、`CONFIG_USB_CONFIGFS=y`

### Requirement: Yocto 同款 DTB 组合

base DTB MUST 由厂商内核树编译并带 `__symbols__`，构建期 MUST 合并板级 `rubikpi3-video.dtbo`：`&venus`
的 `compatible` 为 `qcom,qcm6490-iris-vpu`，含 `non-secure-cb` 子节点
（`compatible = "qcom,vidc,cb-ns"`，`iommus = <&apps_smmu 0x2180 0x20>`）。系统 MUST NOT 合并把 GPU
改为 KGSL 的 graphics overlay、camera overlay 或 `rubikpi3-overlay.dtbo`。rootfs `/boot` 与 `dtb.bin` 中的
DTB MUST 相同。

#### Scenario: 合并结果

- **WHEN** 构建 boot 组件
- **THEN** 最终 DTB 的 venus 节点 compatible 为 `qcom,qcm6490-iris-vpu`，GPU 节点 compatible 不含
  `qcom,kgsl`，且 `/boot` 中的 DTB 与 `dtb.bin` 内 `combined-dtb.dtb` 字节一致

### Requirement: EL1 下 DSP 与硬件编码同时可用

所有 RUBIK Pi 3 目标 MUST 刷写固件包默认（Gunyah）`xbl_config`，MUST NOT 声明 `ufs_file_overrides`，
Linux 运行在 EL1。内核 MUST 以 out-of-tree 模块提供 CodeLinaro `video-driver`
（`video.qclinux.1.0.r1-rel` @ `80f2b25ae580d0cd8cf30ac5e299d7d526e3e995`）编译的 `iris_vpu.ko`，
加载 `qcom/vpu-2.0/vpu20_1v.mbn`。ADSP 与 CDSP MUST 由内核经 PAS 加载并进入 running。

#### Scenario: 配置为 EL1

- **WHEN** 求值任一 RUBIK Pi 3 目标
- **THEN** `bootloader` 不含 `ufs_file_overrides`，`kernel.oot_modules` 含产出 `iris_vpu.ko` 的条目

#### Scenario: 硬件编码不复位

- **WHEN** 刷写 `default` 后启动并对 720p NV12 执行 H.264 硬件编码
- **THEN** 无 `/dev/kvm`，`iris_vpu` 已加载，输出有效 H.264 码流且设备不复位

#### Scenario: DSP 可用

- **WHEN** 刷写 `default` 后启动
- **THEN** ADSP 与 CDSP remoteproc 状态为 running，FastRPC `GET_DSP_INFO` 与 `INIT_ATTACH` 在两者上均成功

## REMOVED Requirements

### Requirement: 上游 DTS 修复 backport

**Reason**: 内核改为厂商树 `rubikpi-ai/linux`，其中已包含 RUBIK Pi 3 的 DTS、LT9611 Port B 连接与驱动支持，
针对 mainline 7.0.2 的 backport 补丁不再适用。
**Migration**: 删除板级 `patches/kernel/0001-0003`；若回到 mainline 基线，从 git 历史恢复。

### Requirement: RUBIK Pi 3 EL2 / EL1 product

**Reason**: 厂商内核在 EL1（Gunyah）下同时提供 DSP 与硬件编码，EL2 仅为绕开 mainline 编码复位而设，
且 EL2 下 DSP 不可用；统一 EL1 后不再需要 product 区分。
**Migration**: `default`/`desktop` 改为 EL1，需重新全量刷写以恢复默认 `xbl_config`；原 `el1` 用户改用
`default`。
