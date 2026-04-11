## 1. FlashConfig 数据模型与 JSON 生成

- [ ] 1.1 定义 `builder/flash.py` 数据模型：`FlashPartition` dataclass（name, offset, type, image）、`PreFlashConfig` dataclass（download_boot）、`FlashConfig` dataclass（platform, flash_tool, board, product, variant, partitions, pre_flash）
- [ ] 1.2 实现 `FlashConfig.to_json(path)` 和 `FlashConfig.from_json(path)` — JSON 序列化/反序列化
- [ ] 1.3 编写 `tests/builder/test_flash.py::TestFlashConfig` — dataclass 构造、JSON 序列化往返、缺失字段报错、路径为相对路径验证
- [ ] 1.4 实现 `FlashConfigGenerator.generate(config, target_dir) -> Path` — 从 FINAL_CONFIG 的 `partitions.entries` + 平台策略的 `partition_image_map()` 生成 flash-config.json
- [ ] 1.5 编写 `TestFlashConfigGenerator` — 从 Rockchip 配置生成 JSON，验证所有分区偏移与 config 一致、镜像路径正确、pre_flash 包含 miniloader

## 2. 平台刷写策略抽象

- [ ] 2.1 定义 `FlashStrategy` 抽象基类：`find_tool()` → Path、`detect_device()` → Optional[DeviceInfo]、`wait_for_device(timeout)` → DeviceInfo、`pre_flash(target_dir, config)`、`write_partition(tool, offset, image)`、`reboot(tool)`、`partition_image_map(config)` → dict
- [ ] 2.2 定义 `DeviceInfo` dataclass（platform, mode, description）和 `FlashError` 异常类
- [ ] 2.3 实现 `RockchipFlashStrategy`：
  - `find_tool()`: 按 `sys.platform` 选择 `tools/{linux|macos}/upgrade_tool/upgrade_tool`，不存在抛 FlashError
  - `detect_device()`: 运行 `upgrade_tool LD`，解析输出匹配 "maskrom"/"loader"
  - `wait_for_device(timeout=30)`: 循环调用 detect_device，每 2 秒一次，倒计时打印，超时抛 FlashError 并附操作指引
  - `pre_flash()`: 运行 `upgrade_tool DB <miniloader>`，sleep 1
  - `write_partition(tool, offset, image)`: 运行 `upgrade_tool WL <offset> <image>`
  - `reboot(tool)`: 运行 `upgrade_tool RD`
  - `partition_image_map()`: 返回 `{"idbloader": "bootloader/idbloader.img", "uboot": "bootloader/u-boot.itb", "boot": "boot/boot.img", "rootfs": "rootfs/rootfs.img"}`
- [ ] 2.4 实现策略注册：`_FLASH_STRATEGIES = {"rockchip": RockchipFlashStrategy}`，`get_flash_strategy(platform) -> FlashStrategy`
- [ ] 2.5 编写 `TestRockchipFlashStrategy` — find_tool 路径选择、detect_device 输出解析（mock subprocess）、wait_for_device 超时测试、partition_image_map 映射验证、write_partition 命令构造

## 3. FlashExecutor 刷写执行器

- [ ] 3.1 实现 `FlashExecutor.__init__(target_dir)` — 读取 flash-config.json → FlashConfig，根据 platform 获取 FlashStrategy
- [ ] 3.2 实现 `FlashExecutor.flash_all(no_wait=False)` — find_tool → wait_for_device → pre_flash → 遍历所有分区 write_partition → reboot
- [ ] 3.3 实现 `FlashExecutor.flash_partition(name, no_wait=False)` — 在 config.partitions 中按 name 查找 → 只写该分区 → reboot
- [ ] 3.4 实现 `FlashExecutor.flash_raw(device)` — 查找 `*_firmware_*.img`，确认提示，`sudo dd if=... of=... bs=4M status=progress conv=fsync` + sync
- [ ] 3.5 实现 `FlashExecutor.list_partitions()` — 打印所有分区名、偏移、镜像路径
- [ ] 3.6 编写 `TestFlashExecutor` — flash_all 调用顺序验证（mock strategy）、flash_partition 按名查找、未知分区报错、flash_raw dd 命令构造、list_partitions 输出

## 4. CLI 入口 (__main__) 与 envsetup.sh 集成

- [ ] 4.1 实现 `builder/flash.py` 的 `__main__` 入口：argparse 解析 `run --target-dir <dir> [partition] [--raw device] [--no-wait] [--list]`
- [ ] 4.2 实现 `builder/flash.py` 的 `generate` 子命令入口：`generate --config <json> --target-dir <dir>`（构建引擎调用，接收序列化的 config JSON）
- [ ] 4.3 修改 `envsetup.sh` 的 `_flange_cmd_flash`：改为 `python3 -m builder.flash run --target-dir "target/${FLANGE_BOARD}/${FLANGE_PRODUCT}/${FLANGE_VARIANT}" "$@"`
- [ ] 4.4 修改 `envsetup.sh` 的 flash 帮助文本：更新 `flange flash` 子命令说明，增加 `--list`、`--no-wait`、`--raw` 选项说明
- [ ] 4.5 编写 CLI 集成测试：`TestFlashCLI` — argparse 参数解析正确、缺失 flash-config.json 报错、--list 输出格式

## 5. 构建引擎集成

- [ ] 5.1 修改 `builder/engine.py`：image 构建完成后调用 `FlashConfigGenerator.generate(config, target_dir)` 生成 flash-config.json
- [ ] 5.2 修改旧 `FlashGenerator` 的调用点（如有）为新的 `FlashConfigGenerator`
- [ ] 5.3 编写 `TestEngineFlashConfig` — build("image") 完成后 target 目录下存在 flash-config.json，内容与 config 分区一致

## 6. 删除旧代码与清理

- [ ] 6.1 删除 `scripts/flange-flash.sh`
- [ ] 6.2 删除 `scripts/flash/common.sh`
- [ ] 6.3 删除 `scripts/flash/rockchip.sh`
- [ ] 6.4 删除 `scripts/flash/` 目录（如已为空）
- [ ] 6.5 确认 `builder/flash.py` 中旧的 `FlashGenerator` 类已被替换（不保留旧代码）
- [ ] 6.6 更新 `tests/builder/test_flash.py`：删除旧的 TestFlashGenerator 测试，确认新测试全部通过

## 7. 文档更新

- [ ] 7.1 更新 `README.md`：`flange flash` 命令说明更新（支持分区名、--list、--no-wait、--raw）
- [ ] 7.2 更新 `docs/app-architecture.md`（如有刷写相关描述）
