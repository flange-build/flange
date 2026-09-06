#!/usr/bin/env python3
"""包内各单元 App 的统一入口。

用法（在 app.yaml 的 build.commands 里）::

    commands:
      - [python3, ../../lib/unit.py, rkmm-gst-bad]

单元自身没有代码，只有一份 app.yaml —— 构建逻辑集中在 lib/ 下，避免 8 份
几乎相同的脚本各自漂移。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"用法: {argv[0]} <unit-app-name>", file=sys.stderr)
        return 2

    app = argv[1]
    import toolkit

    if app == toolkit.REPACK_APP:
        import repack

        repack.build()
        return 0

    if app not in toolkit.UNITS:
        print(
            f"未知单元: {app}；可用: "
            f"{', '.join(sorted([*toolkit.UNITS, toolkit.REPACK_APP]))}",
            file=sys.stderr,
        )
        return 2
    toolkit.build(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
