"""`python3 -m builder.flash` 的入口。

flash 从单个模块拆成包之后，`python3 -m builder.flash` 需要这个文件才能
执行 —— 包不像模块那样可以被直接运行。`envsetup.sh` 的 `flange flash`
走的正是这条路径。
"""

from builder.flash.execute import _cli_main

if __name__ == "__main__":
    _cli_main()
