# qualcommqcs6490-thundercomm-rubikpi3 Specification

## Purpose
定义 Thundercomm RUBIK Pi 3（QCS6490）在 qualcommqcs6490 平台上的板级契约：板级覆盖的 Yocto（QLI 1.5）同款厂商内核基线与 DTB 组合、EL1 下 DSP 与下游视频驱动硬件编码同时可用、位于 UFS boot LUN 的启动固件清单与单会话 edl-ng 全量刷写、UEFI dtb 分区镜像，以及板载 AP6256（bcmdhd）与 Renesas USB3 固件的运行时准备。
## Requirements
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

### Requirement: UFS boot LUN 启动固件清单

系统 MUST 支持板级通过 `bootloader.ufs_rawprogram` 与 `bootloader.ufs_patch` 声明位于 UFS boot LUN 的
启动固件刷写清单。两者 MUST 成对且非空，MUST 同时声明 `bootloader.edk2_firmware`，元素 MUST 是
固件包根目录内的 `.xml` 文件名且不重复。bootloader 构建 MUST 校验：声明的 XML 存在；program
与 patch 不写 LUN0；引用的固件文件存在且不是 Git LFS 指针（由组件产出的 `dtb.bin` 除外）。

板级 MAY 通过 `bootloader.ufs_file_overrides` 把 XML 引用的文件名映射到固件包内的另一文件；
键与值 MUST 是固件包根目录内的单个文件名且不相等，键 MUST 被某条 program 引用且不能是 `dtb.bin`，
替换目标 MUST 通过同样的存在性与 LFS 指针检查。刷写暂存 MUST 以原引用名放置替换后的文件。
被写入文件 MUST 不超过其 program 的 `num_partition_sectors × SECTOR_SIZE_IN_BYTES`（为 0 时不检查）。

#### Scenario: 非法清单在构建前拒绝

- **WHEN** 只声明 `ufs_rawprogram`，或元素含路径分隔符，或缺少 `edk2_firmware`
- **THEN** 配置校验失败并指出字段

#### Scenario: LFS 指针拒绝

- **WHEN** 声明的 XML 引用了 Git LFS 指针文件
- **THEN** 构建与刷写 preflight 均失败，提示移除该 XML 或更换固件包

#### Scenario: 固件超过分区容量时拒绝

- **WHEN** 某固件文件大于其目标分区容量
- **THEN** 构建与刷写 preflight 失败，不写入任何分区

#### Scenario: 文件替换以原引用名写入

- **WHEN** 声明 `ufs_file_overrides: {"xbl_config.elf": "xbl_config_kvm.elf"}`
- **THEN** 暂存目录中的 `xbl_config.elf` 内容为 `xbl_config_kvm.elf`，XML 保持原样

### Requirement: dtb 分区镜像

声明 UFS 启动固件清单时，boot 组件 MUST 额外产出 `dtb.bin`：64MiB FAT16，根目录含
`combined-dtb.dtb`，内容与 rootfs `/boot` 中 GRUB 加载的 DTB 相同（含构建期 overlay 合并）。
该产物 MUST 进入 boot 输出契约；未声明时 boot 输出契约 MUST 保持只有 `boot.img`。

#### Scenario: 输出契约随配置变化

- **WHEN** qcs6490 平台声明 / 未声明 `ufs_rawprogram`
- **THEN** boot 必需产物分别为 `{boot.img, dtb.bin}` / `{boot.img}`

### Requirement: 单会话 UFS 全量刷写

flash-config MUST 以 `ufs_firmware`（loader、rawprogram、patch）记录清单，旧清单缺省为空。
清单非空时 `flange flash` MUST 在等待设备前完成本地 preflight（固件、`dtb.bin`、`raw.img`
齐全，XML 扇区大小与分区配置一致，raw.img 为整扇区），随后在暂存目录生成把 `raw.img` 写到
LUN0 扇区 0 的 `rawprogram0.xml`，并以单个
`edl-ng --loader <loader> --memory UFS rawprogram rawprogram0.xml <rawprogram...> <patch...>`
会话写入。清单为空时 MUST 保持原有 `write-sector` 行为。该板 MUST 拒绝 `--spi-firmware`。

#### Scenario: 单会话命令

- **WHEN** 对声明了清单的目标执行全量刷写
- **THEN** 只调用一次 edl-ng，参数依次为生成的 `rawprogram0.xml`、声明的 rawprogram 与 patch

#### Scenario: LUN0 保护

- **WHEN** 固件 XML 的 program 或 patch 指向 LUN0
- **THEN** 刷写在等待设备前失败，不写入任何分区

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

