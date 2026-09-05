# 验证记录

- 同一环境通过 pyenv Python shim 执行：DYLD_FALLBACK_LIBRARY_PATH 为 None，PyUSB backend 为 None。
- 修复后的入口解析返回当前 pyenv 所选真实 boot-g12.py，--version 成功；同一解释器成功加载 libusb 后端。
- tests/builder/test_amlogic_flash.py 与 test_radxa_zero_flash.py：36 passed，1.90 秒。
- sudo -n 后端探针因需要密码退出，未执行特权后端验证；未向设备传输引导代码或刷写镜像。
- 用户可在自己的交互终端重新运行 flange flash 完成实际设备验证。

归档后：严格规格校验 78 passed；治理测试 136 passed。差异格式检查通过；Ruff 与 HEAD 基线对比无新增问题。
