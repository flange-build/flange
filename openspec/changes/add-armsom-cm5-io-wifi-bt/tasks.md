## 1. BCM43752 / AP6275S 固件声明

- [ ] 1.1 在 `components/board/armsom-cm5-io/config.py` 的 `BOARD["rootfs"]` 追加 `+extra_firmware`：`radxa-pkg/radxa-firmware` repo，`branch=main`，`repo_subdir=radxa-firmware/lib/firmware`，`files=["brcm/fw_bcm43752a2_ag.bin", "brcm/nvram_ap6275s.txt", "brcm/BCM4362A2.hcd"]`，`dest=lib/firmware`；`source` 缺省走 repo
- [ ] 1.2 确认 `.build/sources/extra-firmware/` 下三个目标文件实际存在（本地已 clone 验证：`radxa-firmware/lib/firmware/brcm/` 三件套齐全）
- [ ] 1.3 补 `config.py` docstring：说明 WiFi/BT 方案（BW3752-50B1 / BCM43752 / AP6275S，bcmdhd + 三件套），边界（不预装 BT 用户态栈）

## 2. Kernel patches

- [ ] 2.1 建目录 `components/board/armsom-cm5-io/patches/kernel/`，写 `0001-bcmdhd-set-fw-ampak-path-brcm.patch`：与 `orangepi-cm4` 的 `0002-bcmdhd-set-fw-ampak-path-brcm.patch` 一字不差，启用 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 的 `DHDCFLAGS += -DFW_AMPAK_PATH="\"brcm\""`；commit-style header（`From: flange`、中文 Subject/commentary）
- [ ] 2.2 写 `0002-dts-armsom-cm5-wifi-chip-ap6275s.patch`：改 `arch/arm64/boot/dts/rockchip/rk3576-armsom-cm5.dtsi` 的 `wireless-wlan` 节点 `wifi_chip_type` `"rtl8852bs"` → `"ap6275s"`；中文 commentary 注明原型遗留
- [ ] 2.3 本机用 `git apply --check`（或 `patch --dry-run`）在 `.build/sources/kernel/armsom-cm5-io/` 干跑两条 patch，确认无 hunk 失败
- [ ] 2.4 确认 `patches/kernel/` 仅 0001-0002 两条，无 cm4 的 bootargs / disable-rknpu 残留

## 3. 驱动编出确认

- [ ] 3.1 确认 `CONFIG_BCMDHD`（及依赖）随 `CONFIG_WL_ROCKCHIP=y` 实际编出：检查内核构建后 `.config` 含 `CONFIG_BCMDHD=m`（或 `=y`），产物有 `bcmdhd.ko`（=m 时）或内建符号
- [ ] 3.2 若 3.1 未编出 bcmdhd：在 board 层补一条 defconfig fragment（`CONFIG_BCMDHD=m`）使其编出；若已编出则本步 N/A

## 4. 构建与产物校验

- [ ] 4.1 `source envsetup.sh && lunch armsom-cm5-io-default-release && flange build`，全量出 image 不中断
- [ ] 4.2 在 rootfs staging / mount 产物镜像找 `/lib/firmware/brcm/fw_bcm43752a2_ag.bin` / `nvram_ap6275s.txt` / `BCM4362A2.hcd`，三个文件全存在且非空
- [ ] 4.3 反编 `.build/sources/kernel/armsom-cm5-io/` 编出的 `rk3576-armsom-cm5-io.dtb`（或检查 dtsi 源）确认 `wifi_chip_type` 为 `ap6275s`

## 5. 实机首启验证

- [ ] 5.1 `flange flash`，刷入 ArmSoM CM5 IO 实机
- [ ] 5.2 `ip link` 看到 `wlan0`；`iw dev wlan0 scan | head` 能扫到周围 AP（验证 WiFi RF 与固件加载链路）
- [ ] 5.3 `dmesg | grep -iE 'bcmdhd|brcmf|fw_bcm43752'` 不出现缺 `brcm/` 前缀的固件加载失败
- [ ] 5.4 确认 `/lib/firmware/brcm/BCM4362A2.hcd` 就绪；如需验证 BT，经用户态 patchram 拉起后 `hciconfig -a` 出现 `hci0`（用户态栈非本轮交付，手动验证）

## 6. spec 与 wiki 同步

- [ ] 6.1 校验本 change 的 `specs/rockchip-armsom-cm5-io/spec.md` 所有 Scenario 与上述验证步骤一一对应（无悬空 Scenario）
- [ ] 6.2 更新/新建 `wiki/boards/armsom-cm5-io.md`：写实 WiFi/BT 方案（BCM43752/AP6275S + bcmdhd + 三件套 + 两条 patch），注明 dts 原型遗留 rtl8852bs 的纠正

## 7. change 收尾

- [ ] 7.1 `openspec validate add-armsom-cm5-io-wifi-bt --strict` 通过
- [ ] 7.2 git commit，commit message 中文，遵循 `feat(board/armsom-cm5-io): ...` 前缀风格
- [ ] 7.3 `/opsx:archive add-armsom-cm5-io-wifi-bt` 归档（注意与首版 `add-rk3576-armsom-cm5-io` 的 `rockchip-armsom-cm5-io` spec 合并顺序）
