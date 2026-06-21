## 1. bootloader.py：RK3576 idbloader 经 boot_merger

- [x] 1.1 先写测试 `tests/builder/test_rockchip_idbloader_boot_merger.py`：断言 `_extract_idb_path` 从 `RK3576MINIALL.ini` 的 `[OUTPUT] IDB_PATH=` 正确解析 idblock 文件名；断言 `idbloader_method=="boot_merger"` 时 compile 整段跳过 mkimage、走 boot_merger 拷贝分支（mock `docker.run`/`shutil.copy2`、不实跑），且 `_firmware_dir`/`_ini_prefix` 仍被赋值（collect 不抛）。验证：测试先红（4 fail）✓
- [x] 1.2 `bootloader.py` 加 `_extract_idb_path`（仿 `_extract_output_path`，用**精确** `line.startswith("IDB_PATH=")` 匹配 `[OUTPUT]` 段；已核验与 `PATH=` 不互相误匹配）。验证：1.1 该用例转绿 ✓
- [x] 1.3 `bootloader.py` `compile()` 加 RK3576 idbloader 分支：当 `config["bootloader"].get("idbloader_method")=="boot_merger"`，用 **if/else 整段包住** 现有「`_parse_loader_ini` → `idbloader_spl` → `mkimage`」段（命中即完全跳过、其他 RK35xx 仍走该段）；复用 compile() 末尾**已有的那次** `boot_merger` run（不额外再跑），run 后 `_extract_idb_path` 解析、`shutil.copy2(firmware_dir/idb_path, src_dir/idbloader.img)`；分支内**不得提前 return**（末尾 `_firmware_dir`/`_ini_prefix` 赋值必须执行）；`rkbin.mkimage_chip` 字段**保留不动**。验证：1.1 全绿（6 passed）✓
- [x] 1.4 清理 misdiagnosis 期 `idbloader_spl=="uboot"` 注释/分支段（**用符号定位**该段，非硬编码行号；Option A 不自编 SPL）。验证：`grep idbloader_spl` 在 builder/ 无残留 + 既有 mkimage/spi 测试无回归（stash 比对 0 新失败）✓

## 2. SoC / board 配置切换（含 defconfig 修复）

- [x] 2.1 `rk3576/config.py`：`bootloader` 加 `idbloader_method: "boot_merger"`（SoC 级，所有 RK3576 板适用）；改写该文件中「ROCK 4D 走 prebuilt/不自编」的过时注释。验证：`_load_soc_config("rk3576")["bootloader"]["idbloader_method"]=="boot_merger"` ✓
- [x] 2.2 `radxa-rock-4d/config.py`：移除 `bootloader.prebuilt_spi_image`；加 `flash_spi_loader: True`；**board 层覆盖 `bootloader.defconfig="rock-4d-spi-rk3576_defconfig"`**（DT=rk3576-rock-4d-spi，修「错板」proper，见 design Decision 5）；改写 board config 中「锁 prebuilt、不自编」的 in-code 注释为自编 boot_merger idbloader + 对板 proper。验证：合并配置无 `prebuilt_spi_image`、有 `flash_spi_loader`、`defconfig=="rock-4d-spi-rk3576_defconfig"`、无 `idbloader_spl` ✓
- [x] 2.3 翻转/补审 `tests/config/test_radxa_rock_4d.py`：`test_board_uses_prebuilt_spi` → `test_board_selfbuilds_spi`（断言无 `prebuilt_spi_image`、有 `flash_spi_loader`、`defconfig=="rock-4d-spi-rk3576_defconfig"`、无 `idbloader_spl`、继承 `idbloader_method=="boot_merger"`）；`test_spi_firmware_via_prebuilt_not_selfsynth` → `test_spi_firmware_via_selfbuild`；**补审 `test_soc_layer_inherited`**（repo/branch 仍成立 + 加 idbloader_method 继承断言 + 更新过时注释）。验证：该文件 13 测试全绿 ✓
- [x] 2.4 前置确认：容器内 radxa u-boot `next-dev-v2026.01` `configs/` 含 `rock-4d-spi-rk3576_defconfig`（DT=rk3576-rock-4d-spi）。验证：`ls` 命中 ✓

## 3. flash.py 自编 spi.img 路径确认（不改码）

- [x] 3.1 确认 `flash.py` `FlashConfigGenerator`：ROCK 4D 去 prebuilt 后 `if prebuilt` 为假、自动落入 `elif flash_spi_loader → build_spi_image`（if/elif 互斥）；`build_spi_image` 读的 `idbloader.img`/`u-boot.itb` 由 bootloader `collect` 经 `ARTIFACT_NAMES`（`(bootloader,idbloader)→idbloader.img`、`(bootloader,bootloader)→u-boot.itb`）落到 `target/bootloader/`、文件名匹配。验证：`test_rockchip_spi_loader.py` 全绿 ✓
- [x] 3.2 确认刷写链不变：SPI 固件 `DB miniloader → 切 SPINOR → WL 0 spi.img → RD`；UFS OS 分区仍 `di -p`。验证：`test_rockchip_di_flash.py` + `test_rockchip_spi_loader.py` 全绿 ✓

## 4. 构建 + 离线自检（容器内，不上板）

- [x] 4.1 `flange build radxa-rock-4d-default-debug` bootloader 阶段通过（18.1s，3 patches）：产出 `idbloader.img`（boot_merger，356KB）+ `u-boot.itb`（自编、对板 DT，2.0MB）+ `miniloader.bin`。验证：各产物存在且非空 ✓
- [x] 4.2 离线自检（产物字节级）：`idbloader.img` 头 = `RKNS`（NEWIDB、含 rk3576_boost v1.03）而非旧 `55 aa f0 0f`；`u-boot.itb` 头 = FIT `d00dfeed`；SPL = rkbin 预编 `fwver: v1.08`（非自编 rk2410，锚定 Option A 不自编 SPL）、DDR = rkbin v1.10；proper default DT `fdtfile=rk3576-rock-4d-spi.dtb`（锚定对板修复 B；`evb_rk3576` 仅 SoC 通用 board code）。验证：全部符合预期 ✓
- [x] 4.3 隔离：`idbloader_method` 仅 rk3576 SoC 声明，rk3566/rk3588/rk3588s 无该键 → 走 mkimage else 分支（行为不变）；单测 `test_default_mode_uses_mkimage` + stash 比对 0 新失败已保障字节不变。验证：grep 确认 + 单测绿 ✓（完整 rock5b 构建对比为可选额外项）

## 5. 上板验证（已通过 —— **真因 = gcc-13 工具链**，非本节原计划的 Option A/B SPL 探索；见 design 顶部「真因最终结论」）

- [x] 5.1 上板逐次定位真因：OP-TEE / BL31 版本(v1.19/v1.24) / DDR / u-boot 分支(v2024.10↔v2026.01) / cfdab2f / `0001-ufs-invalidate` patch 均逐一上板证伪；最终反汇编对比两个 gcc（`ufs_send_scsi_cmd`/`ufshcd_cache_flush_and_invalidate` 逐指令一致）锁定真因 = **Ubuntu 24.04 默认 gcc-13 编老 rockchip u-boot 的整体二进制布局，让开机 malloc 的 UFS GPT 读 buffer 落到坏物理地址**。验证：design 顶部根因节落档 ✓
- [x] 5.2 `flange flash --spi-firmware` 刷自编 spi.img（v2026.01 + gcc-10 + OP-TEE + boot_merger）到 SPI NOR（WL 0）。验证：刷写成功 ✓
- [x] 5.3 串口（UART0 1500000）handoff 三点齐见：SPL banner → `Jumping to U-Boot` proper banner → proper 内 UFS 枚举 Samsung KLUDG4UHGC + 加载 kernel。验证：三点齐见、正确启动 ✓
- [x] 5.4 挂 UFS rootfs 启动成功（用户上板确认）。验证：✓
- [x] 5.5 真因非 SPL↔proper 非同源（Option B fallback 不需要）；最终修法 = **全平台 u-boot/kernel 默认 gcc-10**（`builder/base.py` `ComponentBuilder.CROSS` + `docker/Dockerfile` kernel.org gcc-10.5）。验证：base 全局默认落地、各 builder 继承 ✓

## 6. 文档与归档自检（已完成）

- [x] 6.1 `wiki/boards/radxa-rock-4d.md` 更新：bootloader prebuilt → 自编（boot_merger + 对板 defconfig + **gcc-10**），真因订正为工具链。验证：文件更新 ✓
- [x] 6.2 memory `rock-4d-ufs-bootloader-prebuilt.md` 订正：根因 = gcc-13 工具链（gcc-10 修），OP-TEE/缺 boost/DT 错板/分支/源拿不到 等旧结论全部标注证伪。验证：已更新 ✓
- [x] 6.3 spec 同步 + 归档自检。验证：随本次 `openspec archive` 完成 ✓
