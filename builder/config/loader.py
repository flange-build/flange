"""当前构建配置的加载入口。

`.flange/current_config` 只保存 state pointer（board/product/variant），
不缓存完整的 resolved config。每次 build/flash/app 调用 `load_current_config()`
都会从 state 重新调用 `resolve_config` 拿到最新配置——这样：

  - 修改 board/<name>/config.jsonnet、platform/*/config.jsonnet、SoC 配置
    后无需重新 lunch，下次 build 立即生效
  - 避免"config 源文件变了但 current_config 还是老的"导致的构建偏差
  - 保持 lunch 命令的轻量（只写 3 个字段，不做完整解析）

state 文件格式:
    {"board": "...", "product": "...", "variant": "..."}
"""

import json

from builder.config.registry import resolve_config
from builder.config.validate import validate_config
from builder.paths import PROJECT_ROOT


STATE_FILE = PROJECT_ROOT / ".flange" / "current_config"


def load_current_config() -> dict:
    """读取 state 文件 → 重新 resolve_config → 校验 → 返回完整配置字典。

    抛异常：
        FileNotFoundError: state 文件不存在（用户尚未 lunch）
        KeyError:          state 文件缺失 board 字段（文件损坏）
        ConfigError:       配置层硬错误（recovery 启用但缺分区等）
    """
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    board = state["board"]
    product = state.get("product", "default")
    variant = state.get("variant", "release")
    cfg = resolve_config(board, product, variant)
    validate_config(cfg)
    return cfg


def save_state(board: str, product: str, variant: str) -> None:
    """将 target 选择持久化为 state 文件。供 envsetup.sh lunch 调用。"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"board": board, "product": product, "variant": variant},
            f, indent=2, ensure_ascii=False,
        )
        f.write("\n")
