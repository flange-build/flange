"""统一刷写系统 — 构建期生成 + 宿主机执行。

**为什么拆成包**：这两半的生命周期完全不同 ——

  - 构建期（Docker 内）：`generate` 从 FINAL_CONFIG 生成 flash-config.json、
    `spi` 合成 spi.img。它们的产物进组件缓存，改动必须让下游失效。
  - 执行期（宿主机）：`strategy` / `execute` / `console` 调用 rkdeveloptool、
    qdl 一类工具往板子里写。它们不产出任何构建产物。

此前两半挤在一个 1812 行的模块里，缓存只能整文件排除 —— 于是改
flash-config 的生成逻辑不会让 image 失效（漏失效），而改一句刷写工具的
命令行会让整棵树重编（过失效）。拆开之后两边各按自己的性质登记。

本模块只做再导出，既有的 `from builder.flash import X` 全部照旧可用。
"""

from builder.flash.console import (  # noqa: F401
    _c, _err, _header, _info, _ok, _step, _tty, _warn,
)
from builder.flash.model import (  # noqa: F401
    DeviceInfo,
    FlashConfig,
    FlashError,
    FlashIdentityConfig,
    FlashPartition,
    PreFlashConfig,
    _atomic_write_text,
)
from builder.flash.spi import (  # noqa: F401
    SPI_IDBLOADER_OFFSET,
    SPI_IMG_ALIGN,
    SPI_NOR_SIZE,
    SPI_UBOOT_OFFSET,
    build_spi_image,
)
from builder.flash.generate import FlashConfigGenerator  # noqa: F401
from builder.flash.strategy import (  # noqa: F401
    _FLASH_STRATEGIES,
    AllwinnerA733FlashStrategy,
    AmlogicFlashStrategy,
    FlashStrategy,
    QualcommFlashStrategy,
    RockchipFlashStrategy,
    get_flash_strategy,
)
from builder.flash.execute import FlashExecutor, _cli_main  # noqa: F401

# parameter.txt 的渲染属于构建期分区表逻辑，住在 builder/partition/ 下。
# 这里 re-export 只为兼容既有 import 路径。
from builder.partition.rockchip import (  # noqa: F401
    ROOTFS_PARTUUID,
    generate_parameter_txt,
)
