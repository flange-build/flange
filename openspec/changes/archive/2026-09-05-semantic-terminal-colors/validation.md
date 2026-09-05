# 语义颜色验证记录

日期：2026-09-05。

## 实现范围

- `builder/term.py` 的 `Role`、`ANSI_STYLES`、`style` 统一角色与终端能力判断，使用基础终端色和默认前景。
- 公共结果根据实际状态着色；缓存 `miss` 为蓝色正常待执行，`blocked` 为黄色待准备，取消为黄色。
- 构建、刷写和菜单删除重复配色；Shell 就绪提示调用同一 Python 呈现层，不添加命令跟踪。
- Docker 捕获执行结果后再结束步骤；失败不留下绿色成功勾号，步骤、组件和总摘要能表达取消。
- 构建日志入口移除外部工具的 ANSI 颜色；JSON 模式在本次调用期间禁色，并恢复调用者环境。
- 参数解析前识别禁色请求，因此参数自身缺失时的错误诊断同样遵循 `--no-color`。

## 自动化检查

- 公共呈现新增 20 个用例，覆盖颜色角色、状态词出现在路径、stdout/stderr 独立能力、动态替换输出流、
  非 TTY、`TERM=dumb`、`NO_COLOR` 空值与非空值、JSON 过程及环境恢复。
- 公共呈现、工作区和 Shell 首轮定向检查 46 项通过；补充全局解析错误禁色后，公共呈现 20 项通过。
- 构建、Docker 输出捕获、刷写及菜单相关检查覆盖 176 项，全部通过。
- 真实菜单复验后的菜单与公共呈现检查：48 项通过。
- 全量首轮：1729 passed、1 failed、7 skipped。唯一失败是旧用例将 KeyboardInterrupt 与普通异常
  都断言为“构建失败”；按照正式变更的取消契约分别断言“构建已取消”与“构建失败”，保留日志关闭、
  编译诊断不丢失及不显示成功的覆盖，并增加取消不能包含失败摘要的断言。
- 全量复跑：**1730 passed、7 skipped**，耗时 222.34 秒，退出 0。
- 归档前 `openspec validate --all --strict`：78 passed、0 failed。
- 归档同步 `build-output` 与 `cli-experience`：新增 1 条要求、修改 4 条要求。
- 归档后严格规格校验：77 passed、0 failed；规格治理测试：134 passed。
- README、ProjectSpec、CONTRIBUTING、docs 顶层及 Wiki 共 115 份文档：643 个本地链接和锚点有效。
- `git diff --check` 通过。

静态检查：公共 CLI、呈现、终端模块与新测试通过 Ruff 的 E4/E7/E9/F/I 检查及格式化。
扩展到所有本次涉及的运行模块后，唯一剩余项为 `flash/strategy.py` 的 16 个既有未使用或重复导入；
与 HEAD 版本按诊断编号和内容逐一比较，没有新增诊断。本次不删除可能被既有调用者导入的名称。

## 真实终端与可视检查

在临时工作区通过 PTY（伪终端）运行以下命令，记录实际 ANSI 输出：

1. `source envsetup.sh`：退出 0，只有就绪提示；成功与命令使用对应角色，无 xtrace。
2. `flange status`：退出 0，未选目标为黄色，目录与下一步命令为青色。
3. `flange target list radxa-zero3w-default-debug`：退出 0，目标为蓝色。
4. `flange target select radxa-zero3w-default-debug`：退出 0，选择结果为绿色。
5. `flange build --froce`：退出 2，错误前缀为红色，没有执行构建。

将这些记录转换为深浅主题 HTML，并通过 Chrome 截图，人工检查可读性。结果保存在
`docs/assets/terminal-colors.png`，已嵌入 CLI 体验文档。图片使用预览主题，实际颜色跟随用户终端。

另外用真实 PTY 启动目标菜单，分别验证默认颜色与 `NO_COLOR=1`。测试发现 `curses.wrapper`
会先初始化白字黑底默认色对，已通过 `use_default_colors()` 在禁色分支也恢复终端默认前景和背景。
修复后两种模式均能打开、按 `q` 取消、以 130 退出；无颜色模式不产生彩色前景设置，目标状态未写入。
无颜色菜单保留必要的导航绘制与焦点反显，这与普通命令禁用进度动画分别说明。

未运行系统编译或设备部署、刷写；跳过的 Docker 集成测试不作为此次实机验证证据。
