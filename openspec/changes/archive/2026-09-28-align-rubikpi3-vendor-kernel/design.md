## Context

RUBIK Pi 3 当前继承 qcs6490 SoC 层的 mainline `radxa/kernel@linux-7.0.2`，并以 EL2（KVM 版 `xbl_config`）为
默认、另设 `el1` product。实板结论（见 [[thundercomm-rubikpi3]] 与 proposal）：

- EL1（Gunyah）：ADSP/CDSP running；mainline venus（HFI Gen1）+ `vpu20_p1.mbn`（video-firmware 1.0）编码即复位。
- EL2（KVM）：编码可用；TZ 00126.1 不支持 `PAS_GET_RSCTABLE`，跳过资源表后 TZ 接受认证但 DSP 不执行，
  换 TZ 00187 后内核在 3.9 s 的推迟探测阶段被 PS_HOLD 复位。

Thundercomm Yocto（QLI 1.5，`qcom-multimedia-image`）在 EL1 下 DSP 与编码同时可用，关键组成：

| 组成 | Yocto 参考 | 来源 |
|---|---|---|
| 内核 | `rubikpi-ai/linux` 6.6.90 @ `a579877ac6b4`（GitHub `main` 上） | 基于 CLO `kernel.qclinux.1.0.r1-rel` |
| config | `qcom_defconfig` → `qcom_addons.config` → `rubikpi3.config` | 内核树 `arch/arm64/configs/` |
| DTB | `qcom/qcs6490-thundercomm-rubikpi3.dtb` + graphics / camera / video / `rubikpi3-overlay` dtbo | 内核树 + techpack 仓库 |
| 视频 | CLO `video-driver`（`video.qclinux.1.0.r1-rel` @ `80f2b25ae580`），`obj-m += iris_vpu.o` | OOT DLKM |
| 视频固件 | `qcom/vpu-2.0/vpu20_1v.mbn`（video-firmware 2.4.2） | 本 rootfs 已由 `linux-firmware-dragonwing` 提供 |
| DSP 固件 | DTS `firmware-name = "qcom/qcs6490/{adsp,cdsp}.mdt"` | 本 rootfs 已有 `/lib/firmware/updates/qcom/qcs6490/` |
| EL | `xbl_config.elf` == `xbl_config_gunyah.elf` | BOOT 00364 / TZ 00084 |

flange 已具备所需机制：板级 `sources`/`kernel.source`/`kernel.defconfig` 覆盖、`kernel.exclude_patches`、
`kernel.oot_sources`/`oot_modules`、`device_tree.build_overlays` 构建期 fdtoverlay、按 commit 浅克隆。

## Goals / Non-Goals

**Goals:**

- RUBIK Pi 3 全部目标改用 Yocto 同款厂商内核与 config 链，统一 EL1。
- DTB 与 Yocto 的差异只限于刻意不合并的 graphics（KGSL）、camera 与 `rubikpi3-overlay`（仅含 camera）。
- 下游视频驱动以 OOT 模块构建，EL1 下硬件编码不复位；ADSP/CDSP running 且 FastRPC 往返成功。
- 构建系统（builder/）零改动或最小改动，改动集中在板级数据。

**Non-Goals:**

- KGSL 与闭源 Adreno 用户态、CamX、PAL/AGM 音频、Yocto 私有固件包中的 bcmdhd CLM blob。
- SoC 层与 Q6A 的 mainline 基线变化。
- Yocto 的 UKI、systemd-boot、ostree 与 `KERNEL_CMDLINE_EXTRA` 中的性能/调试参数。

## Decisions

### D1 内核源钉住参考工程 commit

板级新增 source `rubikpi-linux`（`https://github.com/rubikpi-ai/linux.git`，commit
`a579877ac6b4afc6df09d8e53564dfb08d9d693f`），`kernel.source` 指向它。选参考构建所用的 commit 而不是
`main` 最新（`b1864ac`），保证与已知可用的 Yocto 镜像逐字对齐；升级到新 commit 作为后续独立变更。
flange 按 commit `--depth=1` 获取，避免克隆 2.65 GiB 全历史。

### D2 config 链照搬 Yocto，SoC 层覆盖继续生效

`kernel.defconfig` 覆盖为 `['qcom_defconfig', 'qcom_addons.config', 'rubikpi3.config']`（与 recipe 中
`KERNEL_CONFIG` + `KERNEL_CONFIG_FRAGMENTS` 顺序一致）。SoC 层 `kernel.config` 中的 builtin 与压缩固件项
（UFS/QMP PHY、`FW_LOADER_COMPRESS_ZSTD`、USB gadget、`MODULE_SIG_FORCE=n` 等）在 6.6 中同样存在，
继续作为末尾覆盖生效；个别在 6.6 不存在或语义不同的符号由板级 `kernel.config` 显式调整。
Yocto 的 `qcom_debug.config` 只在其 DEBUG_BUILD 生效，flange `debug` variant 不引入（variant 只区分 rootfs）。

备选：沿用 SoC 层 radxa fragment 链——在厂商树不存在，否决。

### D3 补丁：排除平台补丁，删除板级 backport，不引入 Yocto recipe 补丁

- `kernel.exclude_patches` 列出平台层 0001-0007（针对 radxa 7.0.2 与 Q6A DTS）。
- 删除板级 0001-0003（mainline backport；厂商树已含 RUBIK Pi 3 的 DTS、LT9611 Port B 与驱动）。
- Yocto recipe 的 0001（`msm_display.ko`，为 KGSL 分离显示模块）与 KGSL 路线绑定，不引入；0002-0006
  （eMMC ICE、IQ-907 EEPROM）与本板无关，不引入。实板若发现依赖再按需以板级补丁补入。

### D4 DTB 组合：厂商基础 DTB + video overlay

`device_tree.name` 保持 `qcs6490-thundercomm-rubikpi3`（厂商树同名、同目录 `qcom/`），GRUB、`dtb.bin` 与刷写
流程无需变化。新增板级 `dtso/rubikpi3-video.dtso`，内容取自 CLO `video-devicetree` 的
`qcm6490-video.dtsi`（`&venus` 改 `compatible = "qcom,qcm6490-iris-vpu"`、`interconnect-names`、
`non-secure-cb` 子节点 `iommus = <&apps_smmu 0x2180 0x20>`，保留原 BSD-3 版权声明），经 `build_overlays`
构建期合并。厂商 Makefile.lib 支持 `DTC_FLAGS_<dtb>=-@`，flange kernel builder 已传入。

不合并：`qcm6490-graphics.dtbo`（把 `&msm_gpu` 改为 `qcom,kgsl`，与 drm/msm 路线冲突）、camera dtbo、
`rubikpi3-overlay.dtbo`（四个 dtsi 中 graphic/bt/wlan 为空，只剩 camera）。

备选：直接从 `video-devicetree` 仓库编译 dtbo——需要新增 techpack DT 源依赖，而内容只有十余行，否决。

### D5 下游视频驱动作为 OOT 模块

板级 source `qcom-video-driver`（`https://git.codelinaro.org/clo/le/platform/vendor/opensource/video-driver.git`，
branch `video.qclinux.1.0.r1-rel`，commit `80f2b25ae580d0cd8cf30ac5e299d7d526e3e995`），`oot_modules`
以 `make -C {kernel_src_abs} M=<driver_dir> ARCH CROSS_COMPILE modules` 编出 `iris_vpu.ko`，安装到
`updates/` 由 udev 按 DT compatible 自动加载。驱动内建全部平台表，无需额外 Kconfig；其 Kbuild 带
`-Werror`，若 flange 工具链（GCC 10.5）与 Yocto（GCC 13）的告警集不同导致失败，在 `pre_build` 中移除
`-Werror`（与 aic8800 的幂等 `git checkout -- .` 先行模式一致）。

固件 `qcom/vpu-2.0/vpu20_1v.mbn` 已由 `linux-firmware-dragonwing` 安装，不新增固件源。厂商树的
in-tree `venus`/`iris` 模块保留编译，但 overlay 改写 compatible 后不会绑定。

### D6 ADSP/CDSP 固件

厂商 DTS 请求 `qcom/qcs6490/{adsp,cdsp}.mdt`，内核固件搜索路径优先 `/lib/firmware/updates/`，由
`linux-firmware-dragonwing` 提供，不新增配置。验收以 remoteproc `running` 与 FastRPC
`GET_DSP_INFO`/`INIT_ATTACH` 往返为准。若 Thundercomm 专用的 `Thundercomm/RubikPi3/adsp.mbn` 与通用
dragonwing 固件在音频等场景出现差异，后续以板级 DT overlay 改写 `firmware-name`。

### D7 统一 EL1，删除 el1 product

products 改为 `['default', 'desktop']`；删除 `ufs_file_overrides`、`rubikpi3-el2.dtso` 及其
`build_overlays`/`boot.overlays.board` 引用。`bootloader.ufs_file_overrides` 作为通用能力保留在
builder 与规格中（测试以夹具覆盖），只是本板不再使用。

### D8 内核命令行

保留 `pcie_pme=nomsi`（Yocto 同款，硬件相关）与 `deferred_probe_timeout=30`（无害，便于 HDMI 链路晚探测）。
不引入 `kpti=off`、`rcu_nocbs`、`rcupdate.rcu_expedited`、`kasan*`、`mitigations`、`swiotlb=128`、
`net.ifnames=0`：前几项是性能/调试取舍，最后一项会改变网卡命名、影响 rootfs 网络配置。

### D9 启动固件不变

保留 boot-assets main@10b8685（BOOT 00430、TZ 00126.1）。它已在本板 EL1 下验证 DSP 可用、保留 LUN3
`usb_fw`；Yocto 的 00364/TZ 00084 仅在出现兼容性问题时作为回退候选。

### D10 Wi-Fi 随厂商 config 改走 bcmdhd

厂商 `rubikpi3.config` 启用 `CONFIG_BCMDHD=m` 并关闭 brcmfmac，dhd 在 `/lib/firmware` 查找
`fw_bcm43456c5_ag.bin`、`nvram.txt`、`config.txt` 与可选的 `clm_bcm43456c5_ag.blob`。前三者取自已在用的
`rubikpi-ai/rubikpi3-firmware`（与其 Makefile install 布局、Thundercomm Ubuntu 固件包一致；fw 与 nvram 与
Yocto rootfs 逐字节相同）。CLM blob 在 Yocto 中来自不公开的 `QCM6490_fw.zip`，缺失时 dhd 打印
`Ignore clm file` 并使用固件内嵌 CLM（9.2.9），实板 2.4/5 GHz 扫描正常，因此不引入。brcmfmac 专用文件与
`radxa-firmware` 源随之删除。

备选：改回 brcmfmac——需偏离 Yocto 的 `rubikpi3.config`，否决。

## Risks / Trade-offs

- [厂商 DT 下 USB 口角色与 mainline 不同，adb gadget 可能不可用] → 首次刷写后优先经串口确认；UDC 缺失时
  以串口 + 有线网 SSH 完成验收，并记录为后续任务。
- [`video-driver` 与 GCC 10.5 的告警差异导致 `-Werror` 失败] → `pre_build` 移除 `-Werror`，保持幂等。
- [CodeLinaro 不支持按 SHA 浅获取] → source 同时声明 branch 与 commit，由 SourceManager 先取分支再定位 commit。
- [下游 `msm_vidc` 的 V4L2 行为与 GStreamer `v4l2h264enc` 不完全兼容] → 先以 `v4l2-ctl` 与 GStreamer 两种
  方式验证；不兼容时记录并评估参考工程的 V4L2 用法，不在本变更引入闭源 gst 插件。
- [desktop 的 GPU/HDMI 在厂商内核 drm/msm 下行为未知，可能回退] → 不作为本变更验收项，板页记录实测结果。
- [bcmdhd 缺少 Yocto 同款 CLM blob，国家/地区功率表使用固件内嵌的旧版 CLM] → 以 ccode=XZ 全球模式运行；
  若需要特定国家信道与功率，再评估 CLM 的合法来源。
- [内核源由 7.0.2 退到 6.6，SoC 层 builtin 覆盖中个别符号不存在] → olddefconfig 会丢弃未知符号；以构建后的
  `.config` 核对 UFS/QMP/USB gadget 为 `=y`。

## Migration Plan

1. 板级配置切换并通过 jsonnet/canonical 测试；构建 `thundercomm-rubikpi3-default-debug`。
2. EDL 全量刷写（`xbl_config` 由 KVM 版改回默认版，必须全量）。
3. 串口确认启动；验收 DSP、视频编码与解码；记录其余子系统状态。
4. 回滚：还原板级配置并重新全量刷写即可回到 mainline + EL2/EL1 方案。

## Open Questions

- 厂商 DT 下 adb（UDC）与有线网是否可用，决定验收通道。
- `iris_vpu.ko` 暴露的编码节点能否直接被 GStreamer `v4l2h264enc` 使用。
