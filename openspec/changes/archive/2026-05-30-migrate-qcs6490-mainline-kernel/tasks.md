## 1. Recon（切换前核实事实，不改代码）

- [x] 1.1 venus 在 mainline 自包含可用：base `sc7280.dtsi:4657` `venus: video-codec@aa00000` 资源齐（`iommus = <&apps_smmu 0x2180 0x20>`、clocks/power-domains/interconnects/opp/`memory-region=<&video_mem>` 全在），默认 `status="disabled"`；**q6a DTS（`qcs6490-radxa-dragon-q6a.dts:1156`）已 `&venus { status="okay"; }`，并在 board reserved-memory 重新声明 `video_mem: video@8fe00000`（line 214，因 line 32 `/delete-node/ &video_mem`）**。无 `qcm6490-addons.dtsi`，include 链是纯 `sc7280.dtsi` + pmic + `qcs6490-audioreach.dtsi`，无任何 venus iommus/子节点删除。注：mainline `qcom,sc7280-venus` 绑定**不需要** video-decoder/video-encoder 子节点（那是 downstream/旧绑定），故 base 节点无此子节点属正常，非缺失。结论：venus 开箱可用，无需任何 patch。
- [x] 1.2 dtb 名不变：Makefile 仍 `qcs6490-radxa-dragon-q6a.dtb`（另有 `-kvm.dtbo` 变体，不用）。compatible=`radxa,dragon-q6a`,`qcom,qcm6490`；venus 仍在 `soc@0`（`sc7280.dtsi` 的 `soc: soc@0`）下，验证脚本路径不变。config.py 的 `dtb`/`dtb_filename` 无需改。
- [x] 1.3 **该分支无 `qcom_defconfig`，只有 arm64 通用 `defconfig`**。其中 VENUS=m / IRIS=m / DRM_MSM=m、UFS：`SCSI_UFSHCD=y` `SCSI_UFSHCD_PLATFORM=y` 但 **`SCSI_UFS_QCOM=m`**、QMP PHY **`PHY_QCOM_QMP=m`**（`PHY_QCOM_QMP_UFS` 默认随父=m）。**关键问题：我们无 initramfs（root=PARTLABEL+rootwait），rootfs 在 UFS 上 → UFS/QMP-UFS-PHY 驱动若为 module 则根本起不来根。** Armbian 对同分支正是把 `SCSI_UFS_QCOM=y` `SCSI_UFSHCD=y` `SCSI_UFSHCD_PLATFORM=y` `PHY_QCOM_QMP=y` `DRM_MSM=y` 全置 builtin（VENUS/IRIS 保持 =m）。→ 决策：`defconfig=["defconfig"]`，新增 enable_configs 强制 builtin：`SCSI_UFSHCD` `SCSI_UFSHCD_PLATFORM` `SCSI_UFS_QCOM` `PHY_QCOM_QMP` `PHY_QCOM_QMP_UFS` `DRM_MSM`。VENUS/IRIS 留 =m（boot 后从 rootfs 加载即可）。无 MODULE_SIG → `disable_configs=[MODULE_SIG_FORCE]` 变冗余但保留无害。
- [x] 1.4 保留/删除：**board `0001-dts-...-PIL-firmware-paths.patch` 已成冗余且会 apply 失败** —— 6.18.2 的 q6a DTS 本身已是 `remoteproc_adsp/cdsp` 指向 `qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn`（line 752/757）、`/delete-node/ &remoteproc_mpss`（line 29）、`/delete-node/ &ipa_fw_mem`（line 27）；patch 上下文（`adsp.mdt`/`&ipa{disabled}`）在新树不存在 → 删除该 board patch。平台 `0001-dwc3-...clear-stall` 在 6.18.2 仍适用：`__dwc3_gadget_ep_set_halt`（gadget.c:2192）仍是 `req/tmp` + `list_for_each_entry_safe(...&dep->started_list...move_cancelled)` + `dwc3_gadget_ep_cleanup_cancelled_requests(dep)` 的旧形态，hunk 上下文匹配 → 保留（adb 自愈相关，归 Task 6.2 复验）。
- [x] 1.5 Armbian 对该分支无内联 kernel patch（patch 目录仅 `patching_config.yaml`），其 `dts-directories: source "dt"` 是 Armbian 自有 overlay 注入机制（与 flange 无关）；flange 直接用 in-tree `qcs6490-radxa-dragon-q6a.dts`（已完整自包含），**无需搬运任何额外 DTS/overlay**。

## 2. 切换内核分支 + 配置

- [x] 2.1 `config.py`：`branch`→`linux-6.18.2`；`defconfig`→`["defconfig"]`（无 qcom_defconfig）；新增 `enable_configs=[SCSI_UFSHCD, SCSI_UFSHCD_PLATFORM, SCSI_UFS_QCOM, PHY_QCOM_QMP, PHY_QCOM_QMP_UFS, DRM_MSM]` 强制 builtin（无 initramfs root-on-UFS 必需）；`disable_configs=[MODULE_SIG_FORCE]` 保留（冗余无害）。配套在 `builder/platforms/qualcommqcs6490/kernel.py` 加 `_apply_enable_configs`（镜像 disable 机制，写 `flange_enable.config` 片段 `CONFIG_X=y` 并 merge）。docstring 更新基线说明。
- [x] 2.2 删除 board `0001-dts-...-PIL-firmware-paths.patch`（6.18.2 q6a DTS 已自带 radxa .mbn 路径 + mpss/ipa 删除，patch 冗余且 apply 失败）；保留平台 `0001-dwc3-...clear-stall`（6.18.2 仍适用，归 6.2 复验）。
- [x] 2.3 删除有害平台 patch `0002-dts-sc7280-enable-venus-video-codec.patch`（Path A 专用、已实板证伪）。

## 3. 构建与静态验证

- [x] 3.1 `flange build kernel` 成功（4753s，慢因裁剪不全+QEMU）：Image 35M + dtb 产出。修了两处构建 bug：① merge_config.sh 在 bind 挂载上 sed-churn 丢临时文件→ kernel.py 改 append+olddefconfig；② 启动关键 UFS/PHY 经 enable_configs 确认 builtin（SCSI_UFS_QCOM/PHY_QCOM_QMP_UFS=y）
- [x] 3.2 反查 dtb：`video-codec@aa00000` `status="okay"` 且 `iommus=<&apps_smmu 0x2180 0x20>` ✓（mainline 自带，无 addons 删除）。注：mainline `qcom,sc7280-venus` 绑定不需要 video-decoder/encoder 子节点（那是 downstream 旧绑定），故 base 无此子节点属正常
- [x] 3.3 `flange build` 整镜像成功（243.8s，kernel 复用缓存）：`image/raw.img` 3.3G + flash-config.json。default product 无 overlay，/boot dtb = 内核阶段已验 venus okay+iommus 的那个

## 4. 实板验证：启动 + UFS（首要门槛）

- [x] 4.1 EDL 刷入镜像成功（edl-ng/Sahara→Firehose，QCS_KODIAK，87s，UFS LUN0），boot loop 板子救活
- [x] 4.2 串口 ttyMSM0 看启动 ✓：mainline 6.18.2 → systemd → rootfs(ext4 sda2) → 登录提示。注：BSP 时串口一直 0 字节是接线问题，板子真启动后 earlycon/ttyMSM0 正常输出
- [x] 4.3 **UFS 稳定 ✓ 无复位**：`ufshcd-qcom 1d84000.ufshc` + `SAMSUNG KLUDG4UHGC` 识别、`sda1/sda2`、EXT4 root 挂载成功。当年 6.18.2 的 UFS HS-G4 PHY 坑，linux-6.18.2 分支已修（PA_TACTIVATE quirk）

## 5. 实板验证：硬件 codec

- [~] 5.1 实板诊断：venus **越过 iommus/dma_mask**（`non legacy binding`，Path B 核心修复坐实），但固件加载 `qcom/vpu-2.0/venus.mbn` 失败 `-2` → probe -22。**根因：固件全是 `.zst`，通用 defconfig 未开 `FW_LOADER_COMPRESS`**（BSP qcom_defconfig 本开着）。修：enable_configs 加 `FW_LOADER_COMPRESS`+`FW_LOADER_COMPRESS_ZSTD`（一并修好 GENI i2c qupv3fw.elf.zst、GPU a660*.zst）。重编中
- [x] 5.2 `/dev/video0`(编码) + `/dev/video1`(解码) 出现，venus iommu_group bound ✓（FW_LOADER_COMPRESS_ZSTD 修复后 venus.mbn.zst 加载成功）
- [x] 5.3 **v4l2-ctl 验收通过**：`platform:qcom-venus` 6.18.2；编码器 NV12→H.264（完整 QP 码控）；解码器 H.264/VP8/VP9。**硬件编解码达成（Path B 核心目标）**

## 6. 既有功能逐项重验（独立推进，不阻塞 codec 里程碑）

- [x] 6.0 有线网 ✓：`enp1s0` UP（DHCP 172.17.1.100，r8169 加载，REALTEK_PHY=y）。修复=从 disable_configs 移除误删的 R8169。GPU 也顺带通了：`/dev/dri/card0`+`renderD128`，a660_sqe/gmu 固件加载（.zst 修复连带）
- [ ] 6.5 音频：soundwire/codec(3200000/3220000/3370000) deferred，等 LPASS pinctrl@33c0000 的 swr-data-state pins；待查（非核心）
- [ ] 6.1 aic8800 wifi：模块在 6.18.2 上编译 + 实板联网
- [ ] 6.2 adb 自愈（usb-gadget）：复核 [[project_q6a_adbd_boot_race]] 的修复在 mainline 是否仍需要/仍生效
- [ ] 6.3 魅族 E3 屏 OOT 三件套（panel_meizu_e3 / sec_ts / sgm37604a）：6.18 KBUILD/DT 绑定适配 + 实板显示/触摸
- [ ] 6.4 GPU drm/msm：Adreno 643 + Mesa freedreno/turnip 实板 GL

## 7. 收尾

- [ ] 7.1 在 `wiki/boards/radxa-dragon-q6a.md` 记录新基线、各功能重验状态（通过/待办/回退）
- [ ] 7.2 作废 Path A 变更 `enable-q6a-venus-codec`（归档/取消）
- [ ] 7.3 按规范提交 commit（中文 message），准备 `/opsx:archive`
