## Why

用户提供的 khadas-vim3 构建日志出现 Git 原始输出与实时状态行交错、用组件数量计算的百分比误导耗时判断，以及同一失败被重复报告。该次构建又在已完成内核和 Bootloader 后因 recoveryctl 默认运行路径与实际安装路径不同而停止；需要同时修复实际缺陷与开发者理解、定位和继续工作的体验。

## What Changes

- 构建终端由单一输出服务管理，Git、Docker 与编译命令的原始输出经统一捕获进入日志，NORMAL 不直接透传工具进度。
- NORMAL 使用目标、阶段、当前动作与结果的简洁层级；移除全宽装饰线、组件比例百分比和耗时占比条，长任务显示实际动作与已耗时。
- 交互终端只保留一个实时状态行；非 TTY、无颜色、窄终端和 JSON 输出保持可读。
- 失败集中展示一次原因、相关命令上下文、日志位置和适用的下一步，外层 Docker/CLI 不重复包装已呈现的内部失败。
- recoveryctl 显式声明 `/usr/sbin/recoveryctl` 运行入口，继续保留构建器对安装清单和执行权限的严格验证。
- 同步 ProjectSpec、CLI 体验审查和开发指南，以实际测试和最小 Docker 验证记录本次范围。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `build-output`: 单一终端输出所有者、简洁层级、真实活动计时、统一命令捕获、失败去重与完整日志。
- `cli-experience`: 一次失败结论、可执行的恢复指引、窄终端与机器输出边界。
- `python-app-packaging`: recoveryctl 的非默认运行入口与既有安装布局保持一致，补充可验证的交付场景。

## Impact

涉及 builder/output.py、构建进程与 Git/Docker 执行通道、engine/CLI 的错误传播、recoveryctl AppSpec、对应回归测试和三份文档。保留已有命令与构建产物契约；输出级别不进入构建输入指纹。

## 非目标

- 不重做目标选择器、设备部署或刷写流程。
- 不用任务数量估算剩余编译时间，不引入未经测量的 ETA（预计完成时间）。
- 不通过关闭运行入口校验或改动 recoveryctl 的系统安装路径绕过错误。
- 不执行真实设备操作，也不以最小 App/日志验证宣称完整系统镜像已经构建通过。
