## ADDED Requirements

### Requirement: RUBIK Pi 3 板级目标

系统 MUST 提供 `thundercomm-rubikpi3` 板级配置，绑定 `platform=qualcommqcs6490`、`soc=qcs6490`，
products 为 `default`、`desktop`，variants 为 `debug`、`release`。内核、图形栈、GRUB 启动与
LUN0 分区几何 MUST 继承 SoC 层；设备树 MUST 为 `qcom/qcs6490-thundercomm-rubikpi3`。
`desktop` MUST 且仅有 `desktop` 启用 `ubuntu-desktop` 硬件特性包。

#### Scenario: 四个目标均通过严格校验

- **WHEN** 求值 `thundercomm-rubikpi3-{default,desktop}-{debug,release}`
- **THEN** canonical 校验通过，kernel source 为 `linux-qcs6490`，DTB 名为 `qcs6490-thundercomm-rubikpi3`

#### Scenario: product 决定桌面

- **WHEN** 求值 `desktop` 与 `default`
- **THEN** 仅 `desktop` 的 custom packages 含 `flange-ubuntu-desktop-config`，rootfs 镜像为 4G

### Requirement: 上游 DTS 修复 backport

板级 kernel patches MUST backport 上游 LT9611 DSI Port B 与 USB QMP PHY 供电修复，且 MUST 能
干净应用到 SoC 层钉住的内核 commit；内核基线升级到已含修复的版本后 MUST 删除对应补丁。

#### Scenario: 补丁应用

- **WHEN** 构建 kernel 组件
- **THEN** 平台与板级补丁全部应用成功，DTS 中 `mdss_dsi0_out` 连接 LT9611 `port@1`

### Requirement: UFS boot LUN 启动固件清单

系统 MUST 支持板级通过 `bootloader.ufs_rawprogram` 与 `bootloader.ufs_patch` 声明位于 UFS boot LUN 的
启动固件刷写清单。两者 MUST 成对且非空，MUST 同时声明 `bootloader.edk2_firmware`，元素 MUST 是
固件包根目录内的 `.xml` 文件名且不重复。bootloader 构建 MUST 校验：声明的 XML 存在；program
与 patch 不写 LUN0；引用的固件文件存在且不是 Git LFS 指针（由组件产出的 `dtb.bin` 除外）。

#### Scenario: 非法清单在构建前拒绝

- **WHEN** 只声明 `ufs_rawprogram`，或元素含路径分隔符，或缺少 `edk2_firmware`
- **THEN** 配置校验失败并指出字段

#### Scenario: LFS 指针拒绝

- **WHEN** 声明的 XML 引用了 Git LFS 指针文件
- **THEN** 构建与刷写 preflight 均失败，提示移除该 XML 或更换固件包

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

rootfs MUST 安装 AP6256 所需的 `brcm/brcmfmac43456-sdio.{bin,clm_blob}`（同源同版本）、
`brcm/brcmfmac43456-sdio.thundercomm,rubikpi3.txt` 与 `brcm/BCM4345C5.hcd`，并 MUST 安装 `bluez`。
系统 MUST 在 sysinit 阶段只读挂载 `usb_fw` 分区到 `/var/usbfw`，使
`/usr/lib/firmware/renesas_usb_fw.mem` 可解析，并重新探测未绑定的 Renesas xHCI；
分区或固件缺失时 MUST 仅记录并继续启动。

#### Scenario: 缺少 usb_fw 不阻塞启动

- **WHEN** 设备没有 `usb_fw` 分区或其中没有固件
- **THEN** 服务成功退出并记录跳过原因，系统继续启动
