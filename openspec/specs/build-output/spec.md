# build-output Specification

## Purpose

定义构建过程的统一输出契约：分层结构、颜色编码、进度与计时、构建摘要、失败诊断与日志持久化，使终端读者与事后排查者各自拿到需要的信息。
## Requirements
### Requirement: 分层输出结构

构建系统 SHALL 将输出分为三个层级：L1 目标、阶段与最终结果，L2 当前动作、缓存决策与关键事件，L3 外部工具原文。NORMAL MUST 使用简洁文本层级，不绘制全宽装饰线、组件比例百分比或耗时占比条；L3 MUST 进入完整日志，只在失败时提取相关上下文。VERBOSE SHALL 在相同层级下展开 L3，QUIET SHALL 保留摘要与必要失败上下文。正文布局 SHALL 采用有限宽度，宽终端不把耗时和状态推到最右侧。

#### Scenario: 默认模式构建输出

- **WHEN** 用户执行 flange build 未指定输出级别
- **THEN** 终端显示目标、阶段、当前动作和最终结果，原始 Git/编译输出只写入日志
- **AND** 不显示资源身份摘要、装饰横线、任务百分比或耗时条

#### Scenario: Verbose 模式构建输出

- **WHEN** 用户执行 flange build -v
- **THEN** 终端展开完整工具输出，并可追加简洁组件耗时记录，不使用耗时占比条

#### Scenario: Quiet 模式构建输出

- **WHEN** 用户执行 flange build -q
- **THEN** 终端保留构建摘要、失败原因、日志位置和适用恢复提示，完整工具输出仍写入日志

### Requirement: 颜色编码标准

构建系统 SHALL 用统一颜色和文字状态表达阶段、成功、警告、失败与复用，并与公共命令、刷写和目标选择共享语义颜色来源。标题、正常需构建与进行中 SHALL 使用蓝色，成功与缓存复用 SHALL 使用绿色，警告、受阻待准备与取消 SHALL 使用黄色，错误与失败 SHALL 使用红色，路径与命令 SHALL 使用青色；正文 SHALL 使用终端默认前景，次要说明 SHALL 降低亮度。

颜色只是辅助信息，输出到非 TTY、`TERM=dumb`、设置 `NO_COLOR` 或指定 `--no-color` 时 SHALL 不输出 ANSI 控制码。状态文字、状态符号与错误原文 SHALL 在降级后保持可读。正常缓存未命中 SHALL 表示待构建而非失败；颜色选择不得改变缓存判断、日志内容或退出码。

#### Scenario: 有能力的交互终端

- **WHEN** 输出为 TTY 且没有禁用颜色
- **THEN** 阶段、正常需构建与进行中使用蓝色，成功和复用使用绿色，警告与受阻待准备使用黄色，失败使用红色，并保留对应状态文字或符号

#### Scenario: 无颜色输出

- **WHEN** 用户指定 `--no-color`，设置包括空值在内的 `NO_COLOR`，设置 `TERM=dumb`，或输出到管道
- **THEN** 输出保留文字含义且不包含 ANSI 颜色与光标控制码

#### Scenario: 正常缓存未命中

- **WHEN** 首次构建或输入变化导致组件需要构建
- **THEN** 需构建状态与执行阶段使用蓝色正常待执行或进行中语义，不呈现黄色警告或红色失败状态

#### Scenario: 缓存复用

- **WHEN** 组件满足缓存复用条件而跳过执行
- **THEN** 复用状态使用绿色，并保留跳过或复用文字与符号，不报告虚构执行耗时

#### Scenario: 用户取消

- **WHEN** 构建收到用户中断且输出到有颜色能力的终端
- **THEN** 取消结果使用黄色，保留取消文字，不显示绿色成功结果

### Requirement: Spinner 动画与计时器

NORMAL 模式的交互终端 SHALL 最多显示一条活动行，内容来自实际阶段、当前动作与已耗时。阶段顺序 MAY 显示真实完成数量，但 MUST NOT 转换成百分比或预计剩余时间。非 TTY、无颜色和 QUIET 模式 MUST 禁用 spinner 与光标重绘；非重绘的 NORMAL/VERBOSE 场景 SHALL 在动作开始时立即输出普通文本，完成时再输出结果，QUIET 保留最终摘要。窄终端 SHALL 按实际可用宽度缩短活动行，完整错误与路径保持可读取。

#### Scenario: 编译进行中

- **WHEN** 编译内核正在执行且终端支持 NORMAL 重绘
- **THEN** 单一活动行显示编译内核与实际已耗时，其他工具输出不能插入活动行正文

#### Scenario: 无动画环境

- **WHEN** 编译输出到管道或无颜色终端
- **THEN** 开始时立即显示正在执行的动作，不等待长命令完成才首次展示状态
- **AND** 输出不含回车重绘或光标控制码

#### Scenario: 不同耗时阶段

- **WHEN** 一个内核阶段耗时远大于其余组件
- **THEN** 输出仅记录真实顺序和已耗时，不把组件数量占比解释为构建时间进度

#### Scenario: 即时通知与实际步骤

- **WHEN** 构建器通过状态接口说明源码已就绪，然后开始实际编译步骤
- **THEN** 状态通知不启动计时，也不自动变成成功动作
- **AND** 步骤结果与耗时来自编译操作的明确开始和结束，不能归属到前一条通知

#### Scenario: 嵌套步骤与时钟调整

- **WHEN** 一个明确的构建步骤包含子步骤，且执行期间系统时间发生调整
- **THEN** 父子步骤各自保留准确结果，单条活动行反映当前动作
- **AND** 耗时来自单调时钟，不因系统时间调整产生负数或跳变

### Requirement: 构建摘要

构建结束后系统 SHALL 输出紧凑结果、真实总耗时与完整日志路径。NORMAL MUST 不重复整张阶段耗时表；VERBOSE MAY 提供无条形图的组件状态与耗时列表。成功、缓存复用、配置关闭和取消 MUST 保持语义区别。结果计数 SHALL 明确表示阶段，不能将 App 汇总阶段完成误称为 App 重新编译数量。失败原因与相关命令上下文 MUST 在一个诊断区集中呈现，适用时给出修复后重试的命令。

#### Scenario: 构建成功摘要

- **WHEN** 本次所有需要的组件成功构建或通过产物验证后复用
- **THEN** 摘要说明构建完成、阶段完成与复用数量、实际耗时和日志位置，不以复用数量伪造编译耗时

#### Scenario: 构建失败摘要

- **WHEN** App 构建中的运行入口校验失败
- **THEN** 摘要指出失败阶段、实际原因、日志位置与修复后重试入口，不在耗时表或外层 CLI 重复同一原因

#### Scenario: 用户取消

- **WHEN** 构建被用户取消
- **THEN** 摘要明确标为已取消，不显示构建完成，不将取消的动作标成成功

### Requirement: 错误上下文提取

外部命令失败时，系统 SHALL 在单一诊断区显示原因与相关命令上下文，优先提取匹配错误模式的行；
无匹配时 SHALL 展示有限的命令输出尾部。失败命令的诊断 MUST 随对应异常保存，后续清理或其他命令不得覆盖。
正常成功命令的旧输出，以及已被业务处理并恢复的失败输出，MUST NOT 被当作后续无关配置错误的原因。
清理另有失败时 SHALL 保留主操作异常及附加清理信息；没有主操作异常时，清理自身失败 SHALL 独立呈现。
完整输出和 traceback SHALL 保留到日志；终端不使用全宽错误框，失败摘要只提供一处完整日志位置。

#### Scenario: 编译错误提取

- **WHEN** make 以非零退出并输出 error 或 undefined reference
- **THEN** 诊断区显示对应命令与相关错误上下文一次，完整编译输出保留在日志

#### Scenario: 无匹配错误模式时兜底

- **WHEN** 命令失败且没有已知错误模式
- **THEN** 诊断区显示该失败命令的有限尾部上下文，不能混入更早成功命令的输出

#### Scenario: apt 错误提取

- **WHEN** apt-get 或 dpkg 失败
- **THEN** 系统保留 E: 或 dpkg: error 等相关行与命令信息，并在最终诊断区展示

#### Scenario: APT 失败后成功清理

- **WHEN** APT 因 sudo 解包权限错误抛出异常，随后执行恢复文件和 umount 清理命令
- **THEN** 最终诊断仍显示该 APT 异常的包名、路径和 Permission denied 上下文
- **AND** 清理命令的完整输出保留在日志，不替换 APT 失败快照

#### Scenario: 已处理失败不会污染后续异常

- **WHEN** 一次可恢复命令失败被业务捕获，后续操作另抛无关配置异常
- **THEN** 配置异常不借用旧失败的诊断，当前命令的活动缓冲仍按命令边界重置

#### Scenario: 清理自身失败

- **WHEN** 清理命令是本次操作唯一失败，或在主操作异常之后另抛异常
- **THEN** 各异常保留自身的命令上下文，主操作异常与附加清理错误可被诊断，没有主操作异常时呈现清理错误

### Requirement: 日志持久化

系统 SHALL 将完整构建输出写入 `WorkspaceContext.target_dir/build.log`，不含 ANSI 控制码。
系统与独立 App/Package 构建 SHALL 在取得目标锁后初始化日志，轮转已有日志后再开始新构建，
并在成功、失败或取消时关闭日志。终端摘要 SHALL 提供完整日志路径。

#### Scenario: 独立资源构建

- **WHEN** 用户在外部工作区执行 `flange app build` 或 `flange package build`
- **THEN** 原始工具输出写入该工作区目标日志，终端默认只显示阶段与摘要

#### Scenario: 并发与失败

- **WHEN** 第二个构建等待相同目标锁，或执行中的构建失败或取消
- **THEN** 等待者不会提前轮转日志，执行者保留完整日志且不会呈现成功摘要

### Requirement: 统一输出接口

一次构建 SHALL 由单一 BuildOutput 实例拥有终端呈现。构建模块的用户可见状态 MUST 通过该接口；Git、Docker 内编译及其他子进程 stdout/stderr MUST 经过捕获通道写入完整日志，再由输出级别决定是否显示。构建管线 MUST NOT 让原始工具进度与活动行同时直写终端。没有构建输出服务的独立工具调用 MAY 使用普通进程执行，不能由此绕过已建立的构建会话。

#### Scenario: 构建模块输出

- **WHEN** 构建模块需要说明当前动作或关键结果
- **THEN** 使用注入的 BuildOutput 状态接口，不直接 print 或 logging.info 到终端

#### Scenario: Git 源码准备

- **WHEN** 源码准备执行 fetch、reset、clean 或 worktree 操作
- **THEN** 原始 Git 输出进入构建日志，NORMAL 只显示实际源码准备动作和结果

#### Scenario: BuildOutput 未注入的独立调用

- **WHEN** 进程在构建会话之外执行只读命令或单元测试
- **THEN** 可以保留直接进程执行行为，不创建伪构建进度或成功日志

### Requirement: Verbose 级别 CLI 参数

`flange build`、`flange app build` 和 `flange package build` SHALL 支持互斥的
`-v/--verbose` 与 `-q/--quiet`。Python CLI SHALL 将输出级别作为执行参数传给输出服务，
不得混入决定构建内容的配置或指纹。

#### Scenario: verbose 参数

- **WHEN** 用户为构建命令指定 `-v`
- **THEN** BuildOutput 以 VERBOSE 级别显示完整工具输出并继续记录日志

#### Scenario: quiet 参数

- **WHEN** 用户为构建命令指定 `-q`
- **THEN** BuildOutput 只呈现摘要与必要的失败上下文

#### Scenario: 默认级别

- **WHEN** 用户不指定输出级别
- **THEN** 构建使用 NORMAL 级别，完整编译器输出仍写入日志

### Requirement: Warning 仅 verbose 显示

构建过程中的 warning 信息（如 GCC warning）SHALL 仅在 VERBOSE 模式下显示。

#### Scenario: 默认模式忽略 warning

- **WHEN** 外部命令输出包含 `warning:` 行且输出级别为 NORMAL
- **THEN** 系统不在终端显示该 warning 行（但写入 build.log）

#### Scenario: verbose 模式显示 warning

- **WHEN** 外部命令输出包含 `warning:` 行且输出级别为 VERBOSE
- **THEN** 系统将该 warning 行作为工具原始输出，以降低亮度的默认前景色显示

### Requirement: 跨进程失败 SHALL 保留一次根因呈现

内层构建已完整呈现失败后，宿主 Docker 与外层 CLI MUST 传播对应失败状态而不再次包装同一根因。只有明确知道已呈现的失败才能去重；容器启动失败、传输异常和未呈现的外层错误 MUST 仍提供可操作诊断。JSON stdout MUST 保持单一结果文档，机器错误保留真实原因和退出状态。

#### Scenario: 容器内 App 校验失败

- **WHEN** 内层构建因 recoveryctl 运行入口无效而失败并已呈现诊断
- **THEN** 宿主不再追加同一错误或笼统 Docker exit 包装作为新的根因
- **AND** 退出状态仍表示失败

#### Scenario: 容器未能启动

- **WHEN** Docker 在内层输出服务运行前失败
- **THEN** 宿主输出该容器启动失败的实际诊断，不因去重规则将错误吞掉

