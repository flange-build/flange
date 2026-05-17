## 1. 板配置

- [x] 1.1 重写 `components/board/orangepi-cm4/config.py` docstring，明确"本轮只做无屏可启动 + WiFi/BT，DSI 屏适配单独立项"边界；维持 `BOARD["kernel"]["dts"] = "rk3566-orangepi-cm4-base"`；不声明 `boot` 字段（让 `board_overlays` / `default_overlays` 继承 SoC 层空 list）
- [x] 1.2 确认 `components/board/orangepi-cm4/` 下无 `dtso/` 目录（屏适配相关产物全部清退）

## 2. AP6256 固件声明

- [x] 2.1 在 `components/board/orangepi-cm4/config.py` 的 `BOARD["rootfs"]` 追加 `+extra_firmware`：`radxa-pkg/radxa-firmware` repo，`repo_subdir=radxa-firmware/lib/firmware`，`files=["brcm/fw_bcm43456c5_ag.bin", "brcm/nvram_ap6256.txt", "brcm/BCM4345C5.hcd"]`，`dest=lib/firmware`
- [x] 2.2 确认 `.build/sources/extra-firmware/radxa/` 下三个目标文件实际存在（开发期已 clone 到本地，构建期由 SourceManager 增量 ensure）

## 3. Kernel patches

- [x] 3.1 建目录 `components/board/orangepi-cm4/patches/kernel/`，写 `0001-dts-orangepi-cm4-bootargs-fix.patch`：改 `arch/arm64/boot/dts/rockchip/rk3566-orangepi-cm4.dtsi` 第 22 行 chosen.bootargs，删 `root=PARTUUID=614e0000-0000`，加 `firmware_class.path=/lib/firmware`；commit-style header（`From: flange`、`Subject:`、中文 commentary）
- [x] 3.2 写 `0002-bcmdhd-set-fw-ampak-path-brcm.patch`：与 tspi-rk3566 的 0002 patch 一字不差，启用 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 的 `DHDCFLAGS += -DFW_AMPAK_PATH="\"brcm\""`
- [x] 3.3 写 `0003-dts-orangepi-cm4-disable-rknpu.patch`：把 `rk3566-orangepi-cm4.dtsi` 中 `&rknpu` / `&rknpu_mmu` 的 `status = "okay"` 改回 `disabled`，避免 NPU PD ack 超时触发 boot panic
- [x] 3.4 本机用 `git apply --check` 在 `.build/sources/kernel/orangepi-cm4/` 干跑三条 patch，确认无 hunk 失败（实操：neons-core3566-nanob 同款 kernel src 上三条均 clean）
- [x] 3.5 确认 `components/board/orangepi-cm4/patches/kernel/` 仅有 0001-0003 三条 patch，无屏相关 0004/0005/0006 残留

## 4. 构建与产物校验

- [ ] 4.1 `source envsetup.sh && lunch orangepi-cm4-default-release && flange build`，全量出 image 不中断
- [ ] 4.2 在 rootfs staging 找 `/lib/firmware/brcm/fw_bcm43456c5_ag.bin` / `nvram_ap6256.txt` / `BCM4345C5.hcd`，三个文件全存在且非空
- [ ] 4.3 校验 boot 分区 staging 下 `/dtbs/rockchip/overlay/` 不含任何与本 board 相关 dtbo 文件；`extlinux/extlinux.conf` 默认 `fdtoverlays` 行不出现（或不引用本 board overlay）

## 5. 实机首启验证

- [ ] 5.1 `flange flash`，刷入 OrangePi CM4 实机
- [ ] 5.2 首启不再出现 `failed to get ack on domain 'npu'` / `Kernel panic - not syncing: panic_on_set_idle set ...`；`dmesg | grep -iE 'rknpu|npu'` 不出现 rknpu_mmu probe 拉起 NPU PD 的错误链
- [ ] 5.3 `dmesg | grep -i 'dw-mipi-dsi-rockchip'` 不应有任何输出（dsi1 disabled，driver 不 probe）
- [ ] 5.4 `cat /proc/cmdline` 确认含 `firmware_class.path=/lib/firmware` 且 `root=` 指向 extlinux 给的 PARTLABEL 而非 dtsi 删除的 PARTUUID
- [ ] 5.5 `ip link` 看到 `wlan0`；`iw dev wlan0 scan | head` 能扫到周围 AP（验证 WiFi RF 与固件加载链路）
- [ ] 5.6 `hciconfig -a` 看到 `hci0`；`hciconfig hci0 up` 不报固件加载错（验证 BT patchram）
- [ ] 5.7 `recoveryctl reboot recovery` 触发 recovery 一次性引导，重启后 `cat /proc/cmdline` `root=` 指向 recovery 分区；再次重启回到 normal 分区（验证删 root= 后切换链路完整）

## 6. spec 与 wiki 同步

- [x] 6.1 校验本 change 的 `specs/rockchip-orangepi-cm4/spec.md` 中所有 Scenario 与上述实机验证步骤一一对应（无悬空 Scenario）
- [x] 6.2 更新 `wiki/boards/orangepi-cm4.md`：写实差异点（无屏 + AP6256 + NPU 禁用 + 三条 patch），并指向 wiki/log.md 的屏适配踩坑记录
- [x] 6.3 更新 `wiki/log.md`：本次 change 收敛过程与屏适配踩坑全部归集到一条 sync 条目，便于未来开屏适配 change 时引用

## 7. change 收尾

- [x] 7.1 `openspec validate orangepi-cm4-bringup-wifi-and-npu-fix --strict` 通过
- [ ] 7.2 git commit，commit message 中文，遵循 `feat(board/orangepi-cm4): ...` 前缀风格
- [ ] 7.3 `/opsx:archive orangepi-cm4-bringup-wifi-and-npu-fix` 归档到 `openspec/changes/archive/`，spec 落到 `openspec/specs/rockchip-orangepi-cm4/`
