## Context

flange 的刷写系统有两套并行实现：

1. **builder/flash.py** — `FlashGenerator` 类，构建引擎调用，在 Docker 内从字符串模板生成 `target/.../flash.sh`。偏移量（0x40、0x4000、0x8000、0x40000）硬编码在 Python 字符串模板中。
2. **scripts/flange-flash.sh** + **scripts/flash/rockchip.sh** — 完整的 shell 刷写框架，支持参数解析、平台检测、设备状态检查、组件级刷写。从 `parameter.txt` 解析偏移。

`envsetup.sh` 的 `flange flash` 命令调用的是 (1) 生成的 flash.sh，更完整的 (2) 未被 CLI 使用。

分区布局在 `platform/rockchip/rk3566/config.py` 的 `partitions.entries` 中声明，由 `builder/partition/` 转换为 `parameter.txt`，但 flash.py 没有读这份配置 — 偏移是手写的。

现有架构：
- `builder/flash.py:FlashGenerator.generate()` — 60 行，字符串模板拼接
- `builder/partition/__init__.py` — `PartitionTable` / `Partition` dataclass
- `builder/partition/rockchip.py` — `RockchipPartitionConverter`，生成 parameter.txt
- `scripts/flange-flash.sh` — 120 行，参数解析+平台路由
- `scripts/flash/common.sh` — 66 行，log/confirm/check 工具函数
- `scripts/flash/rockchip.sh` — 139 行，upgrade_tool 操作封装
- `tools/{linux,macos}/upgrade_tool/` — 平台刷写工具二进制

ProjectSpec §12 规定：刷写在宿主机执行，flash.sh 由构建引擎自动生成，支持组件级刷写。

## Goals / Non-Goals

**Goals:**

- 消除偏移硬编码 — flash 命令从分区配置自动获取偏移
- 统一两套刷写实现为一套纯 Python 方案
- 自动设备检测与等待
- 任意分区级刷写（`flange flash <partition-name>`）
- 保持 target/ 目录可移植（拷到另一台机器上能刷）

**Non-Goals:**

- OTA 更新（远程推送、A/B 分区、增量更新）
- 网络刷写（SSH/fastboot/adb push）
- 非 USB 刷写通道（UART、SD 卡引导等自行操作）
- Allwinner/Qualcomm 平台刷写实现（只预留策略接口）

## Decisions

### 决策 1: 纯 Python 替代全部 shell 刷写脚本

删除 `scripts/flange-flash.sh`、`scripts/flash/common.sh`、`scripts/flash/rockchip.sh`，由 `builder/flash.py` 统一实现。

**理由**:
- shell 脚本解析 JSON 需要 jq 依赖（macOS 不自带），Python 内置 json 模块
- 设备检测逻辑（USB VID:PID 匹配、超时等待、跨平台适配）在 Python 中更易抽象和测试
- `builder/flash.py` 已在项目中存在，扩展而非新增
- 宿主机 Python 3 可用性高（macOS 自带，Linux 主流发行版预装）
- 消除两套实现的维护负担

**替代方案**: 保留 shell 框架，flash.py 只生成 flash-config.json 供 shell 读取。缺点：shell 读 JSON 需要 jq 或 python -c 桥接，仍然是两套代码。

### 决策 2: flash-config.json 作为中间产物

构建时生成 `target/<board>/<product>/<variant>/flash-config.json`，刷写时读取。

```json
{
  "platform": "rockchip",
  "flash_tool": "upgrade_tool",
  "board": "radxa-zero3w",
  "product": "default",
  "variant": "release",
  "partitions": [
    {"name": "idbloader", "offset": "0x40",    "type": "raw",  "image": "bootloader/idbloader.img"},
    {"name": "uboot",     "offset": "0x4000",  "type": "raw",  "image": "bootloader/u-boot.itb"},
    {"name": "boot",      "offset": "0x8000",  "type": "ext4", "image": "boot/boot.img"},
    {"name": "rootfs",    "offset": "0x40000", "type": "ext4", "image": "rootfs/rootfs.img"}
  ],
  "pre_flash": {
    "download_boot": "bootloader/miniloader.bin"
  }
}
```

**理由**:
- 冻结构建时分区配置，`target/` 可移植
- 镜像路径相对于 target_dir，自包含
- JSON 格式 human-readable，调试方便
- flash.py 的两个职责（生成/执行）通过 flash-config.json 解耦

`partitions[].image` 的值是相对于 target_dir 的路径。`pre_flash.download_boot` 同理。

**替代方案**: 刷写时直接读 `.flange/current_config` 获取分区信息。缺点：(1) `.flange/` 在另一台机器上不存在 (2) 用户可能在 build 和 flash 之间 lunch 到其他 target。

### 决策 3: 分区 → 镜像映射由平台策略提供

每个平台的分区名到构建产物路径的映射不同。Rockchip 的映射：

| 分区名 | 镜像路径 | 来源 |
|--------|---------|------|
| idbloader | `bootloader/idbloader.img` | bootloader builder collect() |
| uboot | `bootloader/u-boot.itb` | bootloader builder collect() |
| boot | `boot/boot.img` | image builder（boot 子组件） |
| rootfs | `rootfs/rootfs.img` | rootfs builder collect() |

这个映射由 `RockchipFlashStrategy.partition_image_map(config)` 方法返回，`FlashConfigGenerator` 在生成 flash-config.json 时调用。

**理由**: Allwinner 平台的分区布局和镜像命名与 Rockchip 完全不同（如 Allwinner 用 sunxi-spl 而非 idbloader）。映射必须由平台策略决定。

### 决策 4: FlashStrategy 策略模式

```
builder/flash.py
├── FlashConfig           # flash-config.json 的 dataclass
├── FlashConfigGenerator  # 构建时生成 flash-config.json
├── FlashExecutor         # 刷写时读取 JSON 并执行
├── FlashStrategy (ABC)   # 平台刷写策略基类
└── RockchipFlashStrategy # Rockchip 实现
```

`FlashStrategy` 抽象：

```python
class FlashStrategy(ABC):
    @abstractmethod
    def find_tool(self) -> Path:
        """查找平台刷写工具路径，未找到抛异常"""

    @abstractmethod
    def detect_device(self) -> Optional[DeviceInfo]:
        """检测设备，返回 DeviceInfo 或 None"""

    @abstractmethod
    def pre_flash(self, target_dir: Path, config: FlashConfig):
        """刷写前准备（如 Rockchip 上传 miniloader）"""

    @abstractmethod
    def write_partition(self, tool: Path, offset: int, image: Path):
        """写入单个分区"""

    @abstractmethod
    def reboot(self, tool: Path):
        """重启设备"""

    @abstractmethod
    def partition_image_map(self, config: dict) -> dict[str, str]:
        """返回 {分区名: 镜像相对路径} 映射"""
```

`RockchipFlashStrategy` 实现：

```python
class RockchipFlashStrategy(FlashStrategy):
    TOOL_NAME = "upgrade_tool"
    USB_VID_PID = {"2207:350b": "maskrom", "2207:350a": "loader"}

    def find_tool(self) -> Path:
        platform = "macos" if sys.platform == "darwin" else "linux"
        tool = Path(f"tools/{platform}/upgrade_tool/upgrade_tool")
        if not tool.exists():
            raise FlashError(f"未找到 {self.TOOL_NAME}: {tool}")
        return tool

    def detect_device(self) -> Optional[DeviceInfo]:
        # 调用 upgrade_tool LD，检查输出是否包含 maskrom/loader
        ...

    def pre_flash(self, target_dir, config):
        # upgrade_tool DB miniloader.bin
        ...

    def write_partition(self, tool, offset, image):
        # upgrade_tool WL <offset> <image>
        ...

    def reboot(self, tool):
        # upgrade_tool RD
        ...

    def partition_image_map(self, config):
        return {
            "idbloader": "bootloader/idbloader.img",
            "uboot": "bootloader/u-boot.itb",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }
```

**理由**: 与 `builder/platforms/` 的 ComponentBuilder 策略模式一致。新平台只需添加 XxxFlashStrategy 子类。

### 决策 5: 设备检测双层策略

设备检测分两层：

**快速检测（首选）**：调用平台工具自带的设备列举功能
- Rockchip: `upgrade_tool LD` → 解析输出中的 "Found One MASKROM Device" / "Found One LOADER Device"
- 优点：最可靠，使用平台官方工具，跨 OS 一致
- 缺点：工具本身可能有权限问题

**USB 枚举（降级）**：扫描 USB 设备 VID:PID
- Linux: `subprocess.run(["lsusb"])` → 匹配 `2207:350b` 等
- macOS: `subprocess.run(["system_profiler", "SPUSBDataType"])` → 匹配 Vendor ID/Product ID
- 优点：不需要平台工具有执行权限
- 缺点：只能判断设备存在，无法确认设备模式

`wait_for_device(timeout=30)` 循环调用 `detect_device()`，每 2 秒一次，带倒计时提示：

```
[INFO] 等待设备连接... (28s)
[INFO] 等待设备连接... (26s)
[INFO] 已检测到 Rockchip 设备 (Maskrom 模式)
```

超时后打印平台特定的操作指引（按 Maskrom 按钮等）。

**理由**: 优先用平台工具检测（最准确），USB 枚举作为降级方案。等待机制让用户不需要手动重试。

### 决策 6: CLI 入口改造

`envsetup.sh` 的 `_flange_cmd_flash` 改为调用宿主机 Python：

```bash
_flange_cmd_flash() {
    local target_dir="target/${FLANGE_BOARD}/${FLANGE_PRODUCT}/${FLANGE_VARIANT}"
    if [ ! -f "${target_dir}/flash-config.json" ]; then
        echo "错误: 未找到 flash-config.json，请先执行 flange build"
        return 1
    fi
    python3 -m builder.flash run --target-dir "$target_dir" "$@"
}
```

CLI 语法：

```bash
flange flash                    # 全量刷写（所有分区）
flange flash rootfs             # 刷写 rootfs 分区
flange flash boot               # 刷写 boot 分区
flange flash --raw /dev/sdX     # dd 整盘刷写
flange flash --no-wait          # 跳过设备等待
flange flash --list             # 列出可刷写的分区
```

`python3 -m builder.flash` 的入口：

```python
# builder/flash.py 底部
if __name__ == "__main__":
    # argparse: run --target-dir <dir> [partition] [--raw device] [--no-wait] [--list]
    ...
```

**理由**: `python3 -m builder.flash` 直接利用项目 Python 模块，不需要 pip install，不需要 PATH 配置。`-m` 方式确保 import 路径正确。

### 决策 7: dd 整盘刷写保留

`FlashExecutor.flash_raw(device, target_dir)` 保留 dd 能力：

```python
def flash_raw(self, device: str, target_dir: Path):
    # 查找 *_firmware_*.img
    firmware = next(target_dir.glob("*_firmware_*.img"), None)
    if not firmware:
        raise FlashError("未找到固件镜像")

    size = firmware.stat().st_size
    print(f"镜像: {firmware.name} ({size / 1024 / 1024:.0f} MB)")
    print(f"目标: {device}")
    confirm = input("警告: 将覆盖目标设备全部数据！确认？[y/N] ")
    if confirm.lower() != "y":
        return

    subprocess.run(
        ["sudo", "dd", f"if={firmware}", f"of={device}",
         "bs=4M", "status=progress", "conv=fsync"],
        check=True,
    )
    subprocess.run(["sync"], check=True)
```

dd 模式不走平台策略，因为是通用操作。

## Data Flow

### 构建时（Docker 内）

```
FINAL_CONFIG["partitions"]["entries"]
    │
    ▼
FlashConfigGenerator.generate(config, target_dir)
    │
    ├─ 1. 获取平台策略: RockchipFlashStrategy
    ├─ 2. 调用 strategy.partition_image_map(config)
    │     → {"idbloader": "bootloader/idbloader.img", ...}
    ├─ 3. 遍历 partitions.entries:
    │     对每个分区，从 map 中查找 image 路径
    ├─ 4. 组装 pre_flash 信息（Rockchip: miniloader 路径）
    └─ 5. 写入 target/.../flash-config.json
```

### 刷写时（宿主机）

```
python3 -m builder.flash run --target-dir target/radxa-zero3w/default/release/
    │
    ▼
FlashExecutor.__init__(target_dir)
    ├─ 读取 flash-config.json
    ├─ 解析为 FlashConfig dataclass
    └─ 根据 platform 选择 FlashStrategy
    │
    ▼
FlashExecutor.flash_all()  或  flash_partition("rootfs")
    │
    ├─ 1. strategy.find_tool()
    │     → tools/macos/upgrade_tool/upgrade_tool
    │
    ├─ 2. strategy.wait_for_device(timeout=30)
    │     → 轮询 upgrade_tool LD / lsusb
    │     → "已检测到 Rockchip 设备 (Maskrom 模式)"
    │
    ├─ 3. strategy.pre_flash(target_dir, config)
    │     → upgrade_tool DB miniloader.bin
    │     → sleep 1
    │
    ├─ 4. 遍历分区（或指定单个分区）:
    │     strategy.write_partition(tool, offset, image)
    │     → upgrade_tool WL 0x40 idbloader.img
    │     → upgrade_tool WL 0x4000 u-boot.itb
    │     → upgrade_tool WL 0x8000 boot.img
    │     → upgrade_tool WL 0x40000 rootfs.img
    │
    └─ 5. strategy.reboot(tool)
          → upgrade_tool RD
```

## File Structure

```
builder/
├── flash.py                   # 重写（~300 行）
│   ├── FlashConfig            #   flash-config.json dataclass
│   ├── FlashConfigGenerator   #   构建时生成 JSON
│   ├── FlashExecutor          #   刷写时执行
│   ├── FlashStrategy (ABC)    #   平台策略基类
│   ├── RockchipFlashStrategy  #   Rockchip 实现
│   ├── DeviceInfo             #   设备信息 dataclass
│   ├── FlashError             #   异常类
│   └── __main__ 入口          #   python3 -m builder.flash
│
tests/builder/
├── test_flash.py              # 重写（~200 行）
│   ├── TestFlashConfig        #   JSON 解析测试
│   ├── TestFlashConfigGenerator  # 从 config 生成 JSON
│   ├── TestRockchipFlashStrategy # 命令生成、映射
│   └── TestFlashExecutor      #   执行流程 mock 测试

删除:
├── scripts/flange-flash.sh
├── scripts/flash/common.sh
└── scripts/flash/rockchip.sh
```

## Migration

1. 旧的 `target/.../flash.sh` 不再生成。已有的 flash.sh 在下次 `flange build` 时不会被删除（无害残留），但 `flange flash` 不再使用它。
2. `envsetup.sh` 的 `_flange_cmd_flash` 切换到 `python3 -m builder.flash`，旧入口一次性替换，无过渡期。
3. 测试 `test_flash.py` 完全重写，旧的 4 个测试被新测试覆盖。
