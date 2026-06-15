## 0. 根因调试结论（实机坐实）

- [x] 0.1 扫不到 AP 根因：① mainline `brcmfmac`(=m) 与内建 `bcmdhd`(=y) 争抢 BCM43752 SDIO，brcmfmac 先 bind func1、固件加载失败、`HT Avail timeout` 污染芯片；② **CLM blob 缺失**——`Generic.Min` CLM 不接受 set country（`country setting failed -2`）→ 无可用信道 → 扫描空
- [x] 0.2 实机验证：补 `clm_bcm43752a2_ag.blob` → `country CN` 成功、`CLM: 9.9.8_SS`、扫到 2.4G+5G AP；关 brcmfmac → 无 HT timeout

## 1. rkwifibt OOT 驱动（对齐 radxa-rock5b）

- [x] 1.1 `oot_sources.rkwifibt` = `radxa/rkwifibt` develop（同 rock5b）
- [x] 1.2 `+oot_modules`：`dir=drivers/bcmdhd`，`make_args=[-C {kernel_src}, M={rkwifibt_src}/drivers/bcmdhd, modules, CONFIG_BCMDHD=m, CONFIG_BCMDHD_SDIO=y, ARCH=arm64, CROSS_COMPILE=...]`（绕过 bcmdhd_sdio target 的 `M=$(PWD)` 坑）
- [x] 1.3 `+defconfig` 关内建：`# CONFIG_BCMDHD is not set` + `# CONFIG_BRCMFMAC is not set`
- [x] 1.4 build 验证：`.config` 两项 not set；OOT `bcmdhd.ko` 编出进 `/lib/modules/<rel>/updates/`；镜像 `kernel/drivers/net/wireless/` 下无 rockchip_wlan/brcm 目录

## 2. AP6275S 固件（从 rkwifibt 仓部署，含 CLM）

- [x] 2.1 `+extra_firmware`：`source=oot:rkwifibt`，`repo_subdir=firmware/broadcom/AP6275S`，files=`wifi/{fw,nvram,clm}` + `bt/BCM4362A2.hcd`，`dest=lib/firmware/brcm`
- [x] 2.2 debugfs 确认 rootfs.img `/lib/firmware/brcm/` 含四件套（**clm_bcm43752a2_ag.blob 29225B**）

## 3. OOT bcmdhd 固件路径（modprobe.d overlay）

- [x] 3.1 `overlay/etc/modprobe.d/bcmdhd.conf`：`options bcmdhd firmware_path=/lib/firmware/brcm/fw_bcmdhd.bin nvram_path=/lib/firmware/brcm/nvram.txt`（覆盖 OOT 默认 Android 路径）
- [x] 3.2 实机 reboot 验证：开机 [8.2s] bcmdhd 自动带 param 加载、`Final fw_path=/lib/firmware/brcm/fw_bcm43752a2_ag.bin`、fw+nvram+clm open success、country CN、扫到 AP
- [x] 3.3 debugfs 确认 overlay 进 rootfs.img `/etc/modprobe.d/bcmdhd.conf`

## 4. dts 芯片型号对齐

- [x] 4.1 `patches/kernel/0001-dts-armsom-cm5-wifi-chip-ap6275s.patch`：`wifi_chip_type` `rtl8852bs`→`ap6275s`（实机确认 `wlan_platdata: wifi_chip_type = ap6275s`）

## 5. 实机验证（端到端已过；纯净 flash 待最终确认）

- [~] 5.1 `flange flash` 刷入全新 default-debug build（不带手动修改）——上一 build + config 同款 overlay 已 reboot 端到端验证，全新镜像 debugfs 确认含全部产物；纯净 flash 留作最终确认
- [x] 5.2 实机 `lsmod` 仅 OOT bcmdhd（`updates/bcmdhd.ko`），无 brcmfmac、无 HT timeout
- [x] 5.3 `dmesg` 确认 `Final fw_path=/lib/firmware/brcm/fw_bcm43752a2_ag.bin`、`country CN`、`Firmware up`
- [x] 5.4 `nmcli dev wifi list` 扫到 2.4G+5G AP（wlan0 disconnected 可用）
- [x] 5.5 BT：`/lib/firmware/brcm/BCM4362A2.hcd` 就绪（BT 用户态栈非本轮交付）

## 6. spec 与 wiki 同步

- [x] 6.1 校验 `specs/rockchip-armsom-cm5-io/spec.md` 所有 Scenario 与验证步骤对应
- [x] 6.2 更新 `wiki/boards/armsom-cm5-io.md`：写实 WiFi/BT OOT 方案 + 调试三连坑（brcmfmac 冲突、CLM 缺失→country failed、OOT 固件路径 Android 默认、bcmdhd_sdio M=$(PWD) 坑）

## 7. change 收尾

- [ ] 7.1 `openspec validate add-armsom-cm5-io-wifi-bt --strict` 通过（方案改动后复跑）
- [ ] 7.2 git commit，中文，`feat(board/armsom-cm5-io): ...` 前缀
- [ ] 7.3 `/opsx:archive add-armsom-cm5-io-wifi-bt` 归档（注意与首版 spec 合并顺序）
