> ⚠️ **归档说明（2026-06，用户决定）**：本变更以**代码 + spec 完成**归档 —— §1–§3、§5 已完成（其中 2.3 / 3.1 / 3.2 的描述按实施期演进改用 `prebuilt_spi_image` + `flash_whole_disk`，见各项与 design Decision 6）。**§4 构建验证 + §6 上板验证（串口 / SSH / AIC8800 WiFi/BT）整体推迟为后续 follow-up**：调试期已用**官方 spi.img** 实测 U-Boot 枚举 UFS、extlinux、挂 rootfs、串口 + SSH（design「正面收获」），但最终这套 **prebuilt-URL config** 的 `flange build` + `flange flash` 全链路尚未实跑一遍。下列 §4 / §6 的 `[ ]` 项即该 follow-up 范围（已知缺口，非本次归档阻塞）。

## 1. image.py 扇区参数化（默认 512 不变）

- [x] 1.1 先写测试：`tests/builder/test_rockchip_image_sector.py` —— 断言 `sector_size` 缺省 512 时 offset/size 解析与现状一致；断言 `sector_size=4096` 时 offset 按 `off_512 × 512 ÷ 4096` 重算。验证：测试先红（4 fail，512 用例已绿）
- [x] 1.2 `builder/platforms/rockchip/image.py` 把 `SECTOR_SIZE=512` 改为 `_resolve_sector` 从 `partitions.sector_size` 读（缺省 512）；`_resolve_entries` 按目标扇区重算 offset/size（参照 `qualcommqcs6490/image.py`）。验证：1.1 单测全绿
- [x] 1.3 4K 路径 GPT 写入改用 `losetup -b <sector> -f --show` + `parted`（`_write_gpt_loop`，run_privileged 脚本）；512 路径 `_write_gpt_direct` 保持现有 `parted ...B` + `dd bs=512` 原样。验证：512 用例仍绿
- [x] 1.4 4K 路径把 rootfs 分区 Type-UUID 设为 EFI System GUID `C12A7328-F81F-11D2-BA4B-00A0C93EC93B`（并保留固定 PARTUUID 供 cmdline）；512 路径仅设固定 PARTUUID `614e0000-...`。验证：`_write_gpt_loop` 含两条 sfdisk

## 2. flash.py 刷写策略扇区参数化

- [x] 2.1 先写测试：`tests/builder/test_rockchip_flash_sector.py` 断言 `_gpt_slice` 在 4096 时按 4K 计算、512 时 = 旧 33 扇区；`FlashConfig.sector_size` 缺省 512 + roundtrip。验证：测试先红（4 fail）
- [x] 2.2 `builder/flash.py`：`FlashConfig` 加 `sector_size`（缺省 512，from_json/generate 填充）；`RockchipFlashStrategy.write_gpt` 改用 `_gpt_slice(config.sector_size)`，`pre_flash`/`write_partition`/`reboot` 不动。验证：2.1 单测全绿
- [x] 2.3 ~~确认不引入 `flash_whole_disk`~~ **（实施期演进）** UFS 板（声明 `flash_storage`）刷写走 `flash_whole_disk`（`upgrade_tool DI -p parameter.txt`，loader 按设备 LBA 建 GPT），`write_gpt` 见 `config.storage` 早返回；非 UFS 板返回 False、保留 WL 逐分区路线。仍属 `upgrade_tool`、不用整盘 `dd`。验证：`RockchipFlashStrategy.flash_whole_disk` storage-gated（见 design Decision 6）

## 3. board 配置 radxa-rock-4d

- [x] 3.1 先写测试：`tests/config/test_radxa_rock_4d.py`（仿 `test_radxa_rock5b.py` + `test_rk3576_soc.py`）断言 board 自动发现 + 字段：`soc=rk3576`、`platform=rockchip`、`dts=rk3576-rock-4d`、~~`bootloader.defconfig=rock-4d-rk3576_defconfig`~~ **`bootloader.prebuilt_spi_image`（`{url, sha256}`，实施期演进）**、`partitions.sector_size=4096`。验证：测试先红
- [x] 3.2 新建 `components/board/radxa-rock-4d/config.py`：`BOARD` 字典声明上述身份字段 + ~~`bootloader.defconfig` 覆盖~~ **`bootloader.prebuilt_spi_image`（构建期 url+sha256 下载预编 spi.img，不自编 u-boot；见 design Decision 6）** + `partitions` 整块覆盖（4096 sector_size，boot/recovery/rootfs entry 按 SoC 512B 布局等比例换算到 4K，保字节偏移一致；rootfs `grow_on_first_boot`）。验证：3.1 单测转绿
- [x] 3.3 校验合并配置 `validate_config` 通过（recovery 默认开启，partitions 含 recovery entry）。验证：解析 `radxa-rock-4d-default-debug` 合并配置无报错
- [x] 3.4 确认 SoC 层 `rk3576/config.py` 未被改动（`partitions` 仍 512B eMMC）。验证：`git diff` 该文件为空 + `test_rk3576_soc.py` 仍全绿
- [x] 3.5 先写测试：`test_radxa_rock_4d.py::TestROCK4DWifiAIC8800` 断言合并配置含 `aic8800` oot_source、WiFi+BT oot_modules、`aic8800-d80` firmware。验证：测试先红（3 fail）
- [x] 3.6 board 配置加 AIC8800D80 USB WiFi/BT（`radxa-pkg/aic8800` OOT：`aic_load_fw`+`aic8800_fdrv`+`aic_btusb` + 固件部署 `/lib/firmware/aic8800D80/`），复用 rock5c-lite 模板。验证：3.5 单测全绿 + `validate_config` 通过

## 4. 构建验证（容器内，不上板）

- [ ] 4.1 （follow-up）`flange build radxa-rock-4d-default-debug` 全链路通过：bootloader（**prebuilt spi.img url 下载 + miniloader**，非自编 idbloader/itb）、kernel（含 rk3576-rock-4d.dtb + UFS 驱动）、rootfs、image。验证：各组件产物存在且非空
- [ ] 4.2 校验产出 `raw.img` 的 GPT 按 4096B 扇区写入（`gdisk -l` / `parted unit s print` 报告 4096 sector size，分区起止扇区符合换算预期，rootfs Type 为 EFI System）。验证：命令输出符合预期
- [ ] 4.3 回归：对一块现有 RK3566/RK3588 板（如 radxa-rock5b）重新构建 image，确认 `raw.img` 与本变更前 byte-identical（512 路径未受影响）。验证：产物哈希一致

## 5. 文档与归档自检

- [x] 5.1 新增 `wiki/boards/radxa-rock-4d.md`（板级要点：RK3576 + UFS、defconfig、串口、open risk 实测点）+ `wiki/boards/index.md` 索引项。验证：文件存在
- [x] 5.2 测试：本变更新增 18 项单测（image 5 + flash 4 + board 9）全绿；全量 `pytest tests/config tests/builder` 失败集与基线逐项一致（47 项均为既有其他在途变更的预存失败，本变更引入 0 新失败，comm -23 为空）。验证：失败集 diff 为空
- [x] 5.3 上板实测 open risk 清单（upgrade_tool WL offset 单位 / maskrom usbplug 写 UFS / 4K GPT 识别）已落档到 design.md Open Questions/Risks + wiki 板级页。验证：清单已落档

## 6. 上板验证（固件构建后实测，本变更交付边界）

- [ ] 6.1 maskrom → `flange flash radxa-rock-4d-default-debug` → 实测 `upgrade_tool` 能否写入 UFS（验证 WL offset 单位假设）。验证：刷写命令成功返回，或记录失败现象触发 dd 回退变更
- [ ] 6.2 串口观察 U-Boot 枚举 UFS + 加载 u-boot.itb + kernel banner（UART0 1500000）。验证：串口可见完整 boot log
- [ ] 6.3 内核挂载 UFS rootfs + systemd 起来 + sshd 可登录。验证：SSH 登入成功
- [ ] 6.4 AIC8800D80 USB WiFi/BT bring-up：aic_load_fw/aic8800_fdrv/aic_btusb 加载，`/lib/firmware/aic8800D80/` 固件命中，WiFi 能扫到 AP、BT 能 hciconfig up。验证：dmesg 无固件缺失 + `nmcli dev wifi` 有结果
