## 1. board 目录与 config 落地

- [x] 1.1 创建 `components/board/radxa-cubie-a7a/` 目录骨架（仅 `config.py` + `overlay/etc/` 子树，不创建 `dtso/`、`firmware/`、`patches/`）
- [x] 1.2 编写 `components/board/radxa-cubie-a7a/config.py`：声明 `A733_VENDOR_OVERLAYS`（复制 a7z 全集，删除 `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo` 那一行）与 `AIC8800_RADXA_REPO` / `AIC8800_RADXA_COMMIT` / `AIC8800_D80_USB_FIRMWARE_FILES`（与 a7z 字面相同）
- [x] 1.3 在 `config.py` 顶层导出 `BOARD` 字典：`board="radxa-cubie-a7a"`、`soc="a733"`、`platform="allwinnera733"`、`kernel.dts="sun60i-a733-cubie-a7a"`、`kernel_device.board_dts_path="configs/cubie_a7a/linux-5.15/board.dts"`、`bootloader.target="radxa-cubie-a7a"`、`wifi.aic8800_usb=True`
- [x] 1.4 `BOARD["boot"]["vendor_overlays"]` 绑定 `A733_VENDOR_OVERLAYS`；不声明 `board_overlays`（或显式空列表）
- [x] 1.5 `BOARD["boot"]["default_overlays"] = ["cubie-a7a-enable-sunxi-ac101-sound-card.dtbo"]`，并配中文注释说明"HDMI 直出，DSI 屏首版不点亮"
- [x] 1.6 `BOARD["rootfs"]["+extra_firmware"]` 写入 AIC8800 USB 两条 entry（扁平 + 子目录），各字段与 a7z 一致
- [x] 1.7 不在 `BOARD["rootfs"]` 中声明 `panel_firmware` 键
- [x] 1.8 写入文件头 docstring：`"""Radxa Cubie A7A (Allwinner A733) 板级配置"""` + 关键决策的简要注释（vendor_overlays 复用范围、不携带 dtso/panel firmware/patches 的原因）

## 2. overlay 文件

- [x] 2.1 创建 `overlay/etc/usbdevice.conf`，逐字段复制 a7z 模板；仅把 `USB_PRODUCT_NAME` 改为 `"radxa-cubie-a7a"`，文件头注释里 "Cubie A7Z" 改为 "Cubie A7A"
- [x] 2.2 创建 `overlay/etc/modules-load.d/aic8800.conf`，字节复制 a7z 同名文件（`aic_load_fw` + `aic8800_fdrv` 两行）
- [x] 2.3 创建 `overlay/etc/modprobe.d/aic8800.conf`，字节复制 a7z 同名文件（`options aic_load_fw aic_fw_path=/lib/firmware/aic8800_fw/USB`）
- [x] 2.4 用 `diff -r` 比较 `components/board/radxa-cubie-a7a/overlay/etc/modules-load.d/` 与 a7z 同目录，确认 sha256 一致；`modprobe.d/` 同样校验

## 3. 配置层验证（静态 / 不需要 Docker）

- [x] 3.1 执行 `python -m builder.lunch --list`（或 `flange lunch --list`），验证输出含 `radxa-cubie-a7a-default-debug` 与 `radxa-cubie-a7a-default-release`
- [x] 3.2 执行 `flange lunch radxa-cubie-a7a-default-debug`，并通过 `flange config dump`（或等价命令）打印合并后配置，逐项核对 spec 中的字段值（board / soc / platform / kernel.dts / bootloader.target / boot.default_overlays / wifi.aic8800_usb / rootfs.+extra_firmware）
- [x] 3.3 切回 `flange lunch radxa-cubie-a7z-default-debug`，dump 合并后配置，验证 a7z 字段未受影响（特别是 `boot.vendor_overlays` 仍含 `cubie-a7z-reroute-...`）
- [x] 3.4 用 `git status` 与 `git diff --stat` 确认仅触及 `components/board/radxa-cubie-a7a/` 子树与 wiki 文档；`components/platform/allwinnera733/`、其他 board 目录、`builder/` 均无改动

## 4. 内容哈希与增量构建验证（需要已 build 过 a7z）

- [ ] 4.1 在 apply 本变更前先确认 a7z 处于"全组件已构建"状态（`flange build radxa-cubie-a7z-default-debug` 全 cached），如未，先跑一次全量 build 作 baseline
- [ ] 4.2 apply 本变更后再次执行 `flange build radxa-cubie-a7z-default-debug`，确认所有组件命中缓存（输出含 "cached" 或等价标记，不应触发 kernel / bootloader / rootfs 重建）
- [ ] 4.3 抓取 baseline 与 apply 后两次 a7z 各组件产物 sha256（kernel Image / DTB / bootloader boot0_*.bin / boot_package.fex / rootfs tarball / boot.img），逐项比对应 byte-identical

## 5. a7a 实板构建与启动验收（需要 Docker + 实板）

- [ ] 5.1 切到 `flange lunch radxa-cubie-a7a-default-debug`，执行 `flange build`，确认完整链路通：kernel → bootloader → rootfs → image 五组件全部产出，无错误
- [ ] 5.2 验证 kernel 产物：`arch/arm64/boot/dts/allwinner/sun60i-a733-cubie-a7a.dtb` 存在且非空；`_modules_staging/lib/modules/*/extra/` 含 aic8800 模块（aic_load_fw.ko / aic8800_fdrv.ko）
- [ ] 5.3 验证 bootloader 产物：`out/radxa-cubie-a7a/boot0_sdcard.bin`、`out/radxa-cubie-a7a/boot0_ufs.bin`、`out/radxa-cubie-a7a/boot_package.fex` 均存在且非空
- [ ] 5.4 验证 boot.img：mount loop 设备，确认 `/dtbs/allwinner/overlay/cubie-a7a-enable-sunxi-ac101-sound-card.dtbo` 存在且 `/dtbs/allwinner/overlay/cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo` 不存在；`/extlinux/extlinux.conf` 的 `fdtoverlays` 行含 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`
- [ ] 5.5 验证 rootfs：mount 产物，`/lib/firmware/aic8800_fw/USB/fw_patch_8800d80_u02.bin` 存在；`/lib/firmware/aic8800_fw/USB/aic8800D80/fw_patch_8800d80_u02.bin` 存在；`/lib/firmware/panel-mipi-dbi-spi.bin` 不存在
- [ ] 5.6 SD 卡刷写：`flange flash sd /dev/sdX`（或等价 CLI），插入 a7a 实板上电
- [ ] 5.7 串口验收：U-Boot 启动通过、kernel 启动通过、systemd 进入 multi-user.target；`hostname` 输出 `radxa-cubie-a7a`；`dmesg | grep -iE "aic8800|ac101|axp"` 无 panic、无 unbound
- [ ] 5.8 网络验收：`ip link` 含 `wlan0`；`iw dev wlan0 scan | head` 能扫描到 SSID
- [ ] 5.9 音频验收：`aplay -l` 输出含 `sunxi-ac101b` 字样的 card
- [ ] 5.10 SSH 验收：从主机 `ssh flange@<board-ip>` 登录成功（默认 flange/flange 凭据）

## 6. 知识库与归档

- [x] 6.1 新增 `wiki/boards/radxa-cubie-a7a.md`：硬件简介、与 a7z 的差异、首版验收范围、未启用项（DSI 屏 / GPU / PoE / camera）、刷写步骤、AIC8800 USB Wi-Fi 排错指引
- [x] 6.2 在 `wiki/boards/index.md`（或同级索引文件）添加 `radxa-cubie-a7a` 索引项，与现有 a7z 条目并列
- [x] 6.3 在 `wiki/CLAUDE.md`（如有提及板级条目机制）按惯例同步
- [x] 6.4 commit：`feat(board/radxa-cubie-a7a): 新增 Radxa Cubie A7A 板级支持`（含 design 决策摘要）
- [x] 6.5 执行 `openspec validate add-a733-radxa-cubie-a7a`（或等价命令）确认 spec / proposal / design / tasks 全过校验
- [ ] 6.6 全部任务完成后执行 `openspec archive add-a733-radxa-cubie-a7a`（或运行 `/opsx:archive`），把 capability 落到 `openspec/specs/allwinnera733-radxa-cubie-a7a/`
