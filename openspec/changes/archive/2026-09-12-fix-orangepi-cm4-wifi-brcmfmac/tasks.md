## 1. 板级配置改造

- [x] 1.1 改 `components/board/orangepi-cm4/config.jsonnet` 的 `rootfs.+extra_firmware[0].files`：替换为 `brcm/brcmfmac43456-sdio.bin`、`brcm/brcmfmac43456-sdio.txt`、`brcm/brcmfmac43456-sdio.clm_blob`、`brcm/BCM4345C5.hcd` 四项，移除 `brcm/fw_bcm43456c5_ag.bin` 与 `brcm/nvram_ap6256.txt`；同步更新该字段上方说明三件套用途的注释
- [x] 1.2 改同文件 `kernel.+config`：把现有 `if amp then {...} else {}` 条件表达式改为「无条件包含 `CONFIG_BCMDHD: 'n'`」+ amp 条件项合并，确保所有 product/variant 都关掉 bcmdhd；加注释说明 bcmdhd 为 `default y` 的 bool menuconfig、blacklist 无效、必须 Kconfig 层关闭
- [x] 1.3 改同文件顶部 docstring 的 WiFi/BT 段落：由「WiFi 走 SDIO 接 Rockchip OOT bcmdhd」改写为 brcmfmac 路线，记录两驱动抢绑 SDIO func 的踩坑与 CLM blob 的必要性
- [x] 1.4 删除 `components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`；确认 `0001` / `0003` / `0004` 三个文件名与内容未被改动
- [x] 1.5 验证：`lunch orangepi-cm4` 后 `flange status` 无报错，jsonnet 求值通过（对 `default` 与 `amp` 两个 product 各求值一次，确认 `CONFIG_BCMDHD=n` 在两者中都存在）

## 2. 构建验证

- [x] 2.1 `flange build kernel`，确认构建成功；检查生成的 `.config` 中 `# CONFIG_BCMDHD is not set` 且 `CONFIG_BRCMFMAC=m`
- [x] 2.2 确认 kernel 构建日志中不再出现 `0002-bcmdhd-set-fw-ampak-path-brcm.patch` 的应用记录，其余三条 patch 正常应用
- [x] 2.3 `flange build rootfs`，mount 产物镜像核对 `/lib/firmware/brcm/`：三件套 + `BCM4345C5.hcd` 存在且非空，`fw_bcm43456c5_ag.bin` 与 `nvram_ap6256.txt` 不存在
- [x] 2.4 `flange build` 产出完整镜像

## 3. 实机验收

- [x] 3.1 `flange flash` 刷写实机并启动，确认系统正常起来、adb 可登录
- [x] 3.2 验收 WiFi 接口：`ip link` 含 `wlan0`；`dmesg` 含 `brcmfmac: brcmf_c_preinit_dcmds: Firmware: BCM4345/9`，且不含 `Direct firmware load ... failed with error -2`
- [x] 3.3 验收 SDIO 稳定性：`dmesg` 不含 `brcmf_sdio_htclk: HT Avail timeout`，无反复出现的 `mmc2: card 0001 removed`；`lsmod` 与 `/proc/modules` 均无 `bcmdhd`
- [x] 3.4 验收射频：`ip link set wlan0 up` 后扫描，确认同时扫到 2.4G 与 5G AP，且 `wlan0` MAC 不等于 NVRAM 缺省值 `00:90:4c:c5:12:38`
- [x] 3.5 回归确认 BT 未被影响：`hciconfig -a` 含 `hci0`，`dmesg` 无 `Failed to load Broadcom firmware file (-2)`

## 4. 文档同步

- [x] 4.1 更新 `wiki/boards/orangepi-cm4.md`：WiFi 驱动路线改为 brcmfmac，写明固件清单、驱动抢绑踩坑与实机验收命令
- [x] 4.2 在 `wiki/log.md` 追加一条 sync 条目，记录本次路线切换与实测证据
- [x] 4.3 `openspec validate fix-orangepi-cm4-wifi-brcmfmac` 通过后，走 `/opsx:archive` 归档，确认 spec delta 正确落地到 `openspec/specs/rockchip-orangepi-cm4/spec.md`
