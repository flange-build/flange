## Why

flange 的刷写系统存在三个结构性问题：

1. **偏移硬编码**：`builder/flash.py` 生成的 flash.sh 中，分区偏移（0x40、0x4000、0x8000、0x40000）直接写死在脚本模板里。而分区定义已经存在于 `platform/rockchip/rk3566/config.py` 的 `partitions.entries` 中。这违反了"配置驱动"原则 — 改分区布局需要同时改两处，且 flash.py 不会自动同步。

2. **两套刷写体系割裂**：
   - `builder/flash.py` → 生成 `target/.../flash.sh`（简化版，硬编码偏移，无设备检测）
   - `scripts/flange-flash.sh` + `scripts/flash/rockchip.sh`（完整版，解析 parameter.txt，有设备检测和等待）
   - `envsetup.sh` 的 `flange flash` 调用的是前者（简化版），更完整的后者未被 CLI 使用。

3. **check_image_dir 路径 bug**：`scripts/flash/common.sh` 中 `check_image_dir` 使用 `target/${board}/image`，缺少 product/variant 层级，与实际产物路径 `target/<board>/<product>/<variant>/` 不匹配。

4. **设备检测不够健壮**：当前只在执行 flash 时做一次性检测，不支持等待设备就绪（设备可能正在重启），用户体验差。

## What Changes

### 1. 统一为纯 Python 刷写架构

删除全部 shell 刷写脚本，由 `builder/flash.py` 一个模块同时承担**配置生成**和**刷写执行**两个职责：

**删除**：
- `scripts/flange-flash.sh`
- `scripts/flash/common.sh`
- `scripts/flash/rockchip.sh`

**重写**：
- `builder/flash.py` — 配置生成 + 刷写执行 + 平台策略

### 2. flash.py 双职责设计

**职责 A — 生成 flash-config.json（构建时，Docker 内）**

`FlashConfigGenerator.generate(config, target_dir)` 从 `config["partitions"]["entries"]` 读取分区定义，结合平台策略的分区→镜像映射，生成 `flash-config.json`：

```json
{
  "platform": "rockchip",
  "flash_tool": "upgrade_tool",
  "board": "radxa-zero3w",
  "product": "default",
  "variant": "release",
  "partitions": [
    {
      "name": "idbloader",
      "offset": "0x40",
      "type": "raw",
      "image": "bootloader/idbloader.img"
    },
    {
      "name": "uboot",
      "offset": "0x4000",
      "type": "raw",
      "image": "bootloader/u-boot.itb"
    },
    {
      "name": "boot",
      "offset": "0x8000",
      "type": "ext4",
      "image": "boot/boot.img"
    },
    {
      "name": "rootfs",
      "offset": "0x40000",
      "type": "ext4",
      "image": "rootfs/rootfs.img"
    }
  ],
  "pre_flash": {
    "download_boot": "bootloader/miniloader.bin"
  }
}
```

flash-config.json 的价值：把构建时的分区配置快照冻结下来，target/ 目录可以整体拷贝到另一台机器上刷写，不需要源码树。

分区 → 镜像文件的映射关系由平台策略类提供（Rockchip 有自己的映射规则，Allwinner 将来有不同的）。

**职责 B — 执行刷写（flash 时，宿主机直接运行）**

`FlashExecutor` 类，读取 `flash-config.json`，通过平台策略调用刷写工具：

```
flange flash           → FlashExecutor.flash_all()
flange flash rootfs    → FlashExecutor.flash_partition("rootfs")
flange flash --raw /dev/sdX → FlashExecutor.flash_raw(device)
```

### 3. 平台刷写策略抽象

```python
class FlashStrategy(ABC):
    """平台刷写策略基类"""

    @abstractmethod
    def detect_device(self) -> DeviceInfo: ...

    @abstractmethod
    def wait_for_device(self, timeout: int = 30) -> DeviceInfo: ...

    @abstractmethod
    def pre_flash(self, target_dir: Path, config: dict): ...

    @abstractmethod
    def flash_partition(self, offset: str, image: Path): ...

    @abstractmethod
    def reboot(self): ...

    @abstractmethod
    def partition_image_map(self, config: dict) -> dict: ...


class RockchipFlashStrategy(FlashStrategy):
    """Rockchip 刷写策略 — 使用 upgrade_tool"""
    # detect: upgrade_tool LD | grep maskrom/loader
    # pre_flash: upgrade_tool DB miniloader.bin
    # flash_partition: upgrade_tool WL <offset> <image>
    # reboot: upgrade_tool RD
    # USB VID:PID: 2207:350b (maskrom)

    # partition_image_map 返回:
    # {"idbloader": "bootloader/idbloader.img",
    #  "uboot": "bootloader/u-boot.itb",
    #  "boot": "boot/boot.img",
    #  "rootfs": "rootfs/rootfs.img"}
```

平台策略通过 `config["platform"]` 自动选择，遵循现有的框架与策略分离原则。

### 4. 自动设备检测与等待

`FlashStrategy` 子类实现设备检测：

- **Linux**：`lsusb` 扫描 USB VID:PID，或调用平台工具（upgrade_tool LD）
- **macOS**：`system_profiler SPUSBDataType` 扫描，或调用平台工具
- `wait_for_device(timeout=30)`：轮询检测 + 倒计时提示 + 超时报错
- `flange flash` 自动等待设备就绪
- `flange flash --no-wait` 跳过等待（CI 环境）

### 5. envsetup.sh CLI 统一

`_flange_cmd_flash` 改为直接调用 Python：

```bash
_flange_cmd_flash() {
    local target_dir="target/${FLANGE_BOARD}/${FLANGE_PRODUCT}/${FLANGE_VARIANT}"
    python3 -m builder.flash run \
        --target-dir "$target_dir" \
        "$@"
}
```

宿主机直接运行 Python（不走 Docker），因为刷写需要访问 USB 设备。macOS 和大多数 Linux 发行版预装 Python 3。

### 6. dd 整盘刷写保留

`FlashExecutor.flash_raw(device)` 保留 dd 整盘刷写能力：

```
flange flash --raw --device /dev/sdX
```

在 target 目录下查找 `*_firmware_*.img`，确认后 `dd if=... of=/dev/sdX bs=4M status=progress conv=fsync`。

## What Doesn't Change

- 刷写仍在宿主机执行（非 Docker）
- 平台刷写工具不变（upgrade_tool 等二进制保留在 `tools/` 下）
- 分区配置仍在 `platform/<vendor>/<soc>/config.py` 中声明
- `builder/partition/` 模块（PartitionTable、RockchipPartitionConverter）不变
- 构建引擎依赖图不变

## Risks

- **宿主机 Python 依赖**：刷写改为 Python 后，宿主机需要 Python 3。macOS 自带，Linux 大多预装，但极端精简系统可能没有。可接受，因为 flange 本身就需要 Docker + Git 等工具链。
- **macOS 与 Linux USB 检测差异**：设备检测需要分平台实现，需两端测试。
- **flash-config.json 与构建产物路径一致性**：镜像路径是相对于 target_dir 的相对路径，需要与各 ComponentBuilder.collect() 的产物输出路径严格对齐。
