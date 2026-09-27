## Context

Q6A 的 EL2 由 Radxa UEFI 菜单「Hypervisor Override」切换，并由 UEFI 应用
`qcs6490-radxa-dragon-q6a-kvm.dtso`。RUBIK Pi 3 的 Thundercomm/Qualcomm UEFI 没有该菜单，
QLI 的做法是换用 `xbl_config_kvm.elf`，而 flange 的 DTB 由 GRUB `devicetree` 与 dtb 分区提供，
不经 UEFI 应用 overlay，故 EL2 调整须在构建期合并。

## Decisions

### 通过文件替换选择 KVM 版 xbl_config

签名固件不能改字节，只能整文件替换。官方 rawprogram1/2 的 `xbl_config_a/_b` 引用
`xbl_config.elf`；`ufs_file_overrides` 保持 XML 原样，只在构建期校验与刷写暂存时把被引用名
映射到固件包内的替换文件。被替换名必须被某条 program 引用，不能替换组件产物 `dtb.bin`，
替换目标同样做存在性与 Git LFS 指针检查。替代方案是复制并改写 XML，会让官方清单与
flange 生成物混杂，故不采用。

`xbl_config_kvm.elf` 与默认 `xbl_config.elf` 分属两次构建（251205 / 251225），前者缺少后者的
少量 XBL 阶段 pinctrl 条目；它是 Thundercomm 为本板一并发布的官方变体，差异风险由实板验收覆盖。

### EL2 设备树调整

| 属性 | 来源 | 作用 | 7.0.2 消费者 |
|---|---|---|---|
| `&gpu_zap_shader status = "disabled"` | 上游 kodiak-el2 / Q6A | EL2 下由 Linux 切出 GPU 安全模式 | msm adreno zap 加载 |
| `&remoteproc_adsp iommus <0x1800 0x0>` | 上游 kodiak-el2 | ADSP PAS 固件经 Linux 管理的 SMMU 流 | `qcom_q6v5_pas`（`has_iommu`） |
| `&remoteproc_cdsp iommus <0x11a0 0x0400>` | 上游 kodiak-el2 | 同上，CDSP | 同上 |
| `&watchdog status = "okay"` | 上游 kodiak-el2 | EL2 下 APSS 看门狗归 Linux | `qcom-wdt` |
| `&scm qcom,shm-bridge-vmid = SELF_OWNER` | Q6A | SHM bridge 归属 Linux 自身 | `qcom_tzmem.c` |
| `&venus iommus` + `video-firmware { iommus }` | Q6A | Linux 自行加载、启动 venus 固件 | `venus/firmware.c` |

PAS 的 SMMU 流 ID 不能从 fastrpc context bank 推导（lemans 的 CDSP0 fastrpc 为 `0x2141/0x04a0`，
PIL 却是 `0x21c0/0x0400`），因此以 Qualcomm 上游补丁为准。上游 overlay 中的
`remoteproc_mpss` 与 `wifi` 在本板 DTS 已删除，引用会使 fdtoverlay 失败；上游禁用 venus，
本板保留 Q6A 的 `video-firmware` 方案（实板验证硬件编码可用）。Q6A overlay 中的
`qcom,broken-reset` 在 7.0.2 中没有任何驱动读取，Radxa `/chosen` 标记与 PCIe 地址窗口属于其
UEFI/板级，不移植。

### LT9611 驱动补丁

上游 DTS 修复 `ebcf2240a249`（port@1）依赖同系列驱动补丁 `e8bd92c4a0d2`：7.0.2 驱动只接受
port@0 为主 DSI，缺少它时 LT9611 探测失败，msm 显示与 GPU 均无法初始化。该补丁在仅 port@0
时行为不变，作为板级 kernel patch 0003 应用。

## Risks / Trade-offs

- EL2 下若某外设依赖 Gunyah 行为而失效 → 实板逐项复验（启动、UFS、GPU/HDMI、音频、编解码）；
  回退为删除 `ufs_file_overrides` 与 `build_overlays` 后重新全量刷写。
- KVM 版 xbl_config 较旧 → 同上，由实板验收覆盖。

### EL2 下 ADSP/CDSP 与 product 拆分

补齐 `iommus` 后 PAS 越过 `-22`，卡在 `Error in getting resource table: -5`：7.0.2 在无
hypervisor 时通过 SCM 向 TZ 查询资源表，本板固件的 TZ 不支持。实测：

| 固件 | BOOT / TZ | EL2 结果 |
|---|---|---|
| boot-assets main@10b8685 | 00430 / 00126.1 | 启动正常，DSP `-5` |
| boot-assets qli2.0@eaf0c64（只刷 LUN1/2/4/5，保留 LUN3 usb_fw） | 00508 / 00146 | 启动正常，USB3 正常，DSP `-5` |
| Qualcomm QCM6490_bootbinaries 00142 + main XML/CDT | 00569 / 00187 | 退出 UEFI 后内核即停 |

EL1 与 EL2 是硬取舍（EL1：DSP 可用、硬件编码复位；EL2：硬件编码可用、DSP 离线），故以
product 区分：default / desktop 为 EL2，`el1` 为 EL1。三处 EL2 配置（`ufs_file_overrides`、
`boot.overlays.board`、`build_overlays`）只对 EL2 product 生效；固件基线保持 main。

### 分区容量检查

rawprogram 按文件实际大小写入，文件大于 `num_partition_sectors × SECTOR_SIZE` 时会连续写入
相邻分区。套用外来固件的实验证明需要该检查；`num_partition_sectors = 0`（随磁盘剩余空间）跳过。
