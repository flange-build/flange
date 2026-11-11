# AGENTS.md — flange 开发与文档规则

本文件是仓库唯一的 AI Agent（智能代理）规则入口，集中维护共用的工程约定。
用户当前明确指令优先于本文件。产品用法与实现参考统一从 [docs/README.md](docs/README.md) 进入。

## 1. 项目与工作方式

flange 使用 Python、Jsonnet 和 Docker 构建嵌入式 Linux，默认复用 ubuntu-base 与 Ubuntu 软件包，
支持通过 Layer（扩展层）接入其他发行版。不承诺未经同条件测量的速度、严格复现或全硬件支持。

1. 先检查 git status、相关实现、测试和结果文档，保留工作区已有修改。
2. 直接完成“确认问题 → 修改实现 → 验证 → 同步结果文档”的闭环；每个工作单元不超过两小时。
3. 不使用 OpenSpec、Superpowers 或其他 SDD（规格驱动开发）流程；不创建提案、设计草案、任务清单、
   阶段计划、交接记录、归档目录或流程专用命令、技能与 CI（持续集成）门禁。
4. 临时方案、调查与进度留在当前对话；历史演进由 Git 记录。仓库只交付当前有效的结果。
5. 修改前读对应的[架构](docs/build-system-design.md)、[配置](docs/configuration.md)、
   [App](docs/app-architecture.md)或[板卡说明](docs/boards/README.md)。对照实现和证据修正文档矛盾，
   不通过删除失败检查来掩盖问题。
6. 设备刷写、上传 MCU（微控制器）固件或覆盖数据必须在用户授权范围内执行。

## 2. 文档治理

- **只保留结果文档**：操作指南、当前架构与接口参考、板卡/外设说明、已确认的故障原因及处理方法。
  删除过时、重复和中间状态文档前，提取仍有效的结论、限制、接线、验证范围与排障方法。
- **一个主题一个正文入口**：README 是门面与快速开始，docs/README.md 是全局导航，docs/ 放指南和参考。
  组件旁 README 描述该组件的实际构建、接口与维护细节；不另维护 Wiki、规格、评审与路线图副本。
- **唯一规则文件**：Agent 行为、编码、提交、文档与验证规则全部集中于根目录 AGENTS.md。
  不创建或保留子目录 AGENTS、CLAUDE/GEMINI 文件、编辑器 rules、提示词或仓库级 Agent 技能。
  第三方许可证及随源码发布的上游说明保持原归属，不作为 flange 规则。
- **事实与验证分开**：配置存在、单元测试、Docker 编译、镜像生成、实机启动和外设验收分别说明。
  验证注明日期、target（目标）、硬件/介质和实际结论；未测项目写成当前限制。
  新证据替换旧结论，不保留矛盾的阶段叙述、勾选清单或“本轮/下一步”流水账。
- **教程能闭环**：写明前提、运行位置、完整命令、预期结果、产物位置、失败处理与下一入口。
  不把私人目录、/tmp 或旧产物当作读者必须拥有的输入。
- **README 可执行且克制**：用途与能力 → 快速开始 → 支持范围 → 架构 → 文档与贡献。
  使用真实徽章、仓库内图示和清晰表格，不编造性能、CI 或硬件验收结论。
- **同步与校验**：行为变化时更新正文和索引；核对 CLI、schema、注册表、链接、锚点及示例。
  导航使用标准 Markdown 链接，不依赖双括号链接或特定笔记软件。
- 文档、注释、commit message 用中文，代码标识符用英文；专业术语首次标注中文释义。
  标准许可证和第三方原文保持原语言。Markdown 按内容组织标题、表格、代码块，避免重复正文。

## 3. 架构与路径

- 仓库三层：builder/ 放代码，components/ 放配置/补丁/原料，.build/ 放派生物。
  平台规则位于 builder/platforms/，平台数据位于 components/platform/，两者严格分离。
- 运行路径来自显式 WorkspaceContext；builder/paths.py 提供默认锚点与纯路径辅助。
  不通过 cwd、全局 BUILD_ROOT、根目录 target 链接或旧目录名重新猜工作区。
- 工具根、工作区、构建根和用户源码各有归属；目标保存在工作区 .flange/current_config。
  目标为 <board>-<product>-<variant>，共用 config.query.parse_target，不手工拆连字符。
- 目标编译与系统成像在 Docker 内执行，刷写、ADB（Android 调试桥）及设备会话在宿主执行。
  envsetup.sh 只准备 Python 环境和 lunch；业务入口为 flange / python -m builder。
  独立 ESP-IDF 外设固件的现有工具链边界在组件文档明示，不宣称已集成到 flange Docker。
- 内核源码/工作树要求大小写敏感文件系统；rootfs/recovery 活树使用容器原生 /var/tmp。
  不通过禁用目标驱动规避宿主环境问题，不把大小写敏感等同于完整 Linux 权限语义。
- 普通 App/Package 构建默认非特权；系统成像通过 Compose 服务配置按需开启特权。
  DockerRunner 每次显式设置权限环境，不继承宿主同名变量，不给 compose run 传 --privileged。
- 新板优先添加配置、补丁和板级内容；新平台/发行版复用策略接口或扩展层。
  框架缺能力时完善通用抽象和测试，不为具体板型向核心添加临时分支。

## 4. 配置、构建与产物

- 系统配置为 Jsonnet，App 为 app.yaml，Package（功能包）为 package.py:PACKAGE；
  Package Python 是受信任的可执行代码，不是沙箱数据。
- Jsonnet/Libsonnet 第一条非空内容为中文职责注释；特殊值、硬件限制和产品条件就近解释。
  组合顺序为发行版 → platform → SoC → board → 直接启用 Package，每阶段内部按层顺序。
  保留 Jsonnet 原生覆盖、+: 语义及有效设计依据。
- SoC 声明芯片事实，显示路由、介质、软件包和 AMP（非对称多处理）开关属于 board/product。
  架构区分 userspace/kernel/bootloader；Kconfig target 与 CONFIG_* 状态分开。
- 拒绝未知字段、重复 YAML 键、隐式转换和作者注入的派生字段。每个新字段同时具备类型、默认值、
  合法组合、消费者、缓存影响、文档及有效/错误用例。
- 计划、执行、why 与缓存共用 TaskPlan；指纹包含实际配置、源码、补丁、配方、环境、SDK 和上游产物身份。
  树摘要包含内容、类型、权限与链接目标，不以 mtime 或整层 Git HEAD 代替输入身份。
- 缓存命中同时要求输入一致与必需产物有效。输出经 ArtifactManifest 校验后原子发布；
  失败保留上次成功结果，不将半成品、目录存在或旧 .build_hash 当成功。
- 目标持有进程间锁；共享源码、下载和 APT 按真实目录加锁，顺序为目标/资源锁 → APT 锁。
  APT 锁放在缓存旁、不被 clean 删除，完成事务后释放，不覆盖无关编译。
- Phase 1（基础阶段）计划同时驱动 rootfs/recovery 基础执行与缓存；Phase 2（定制阶段）不污染基础缓存。
  解包/快照保留 UID/GID、权限、链接、扩展属性、capability 与 ACL；清理前确认无残留挂载。
- App 名称/path/cwd 共用 AppResolver 与完整依赖闭包，拒绝缺失、循环及同名不同源。
  不在用户源码写构建产物；复制保留链接本身、普通节点权限和空目录。
- PackageBackend 负责格式处理，外部完整包不重打包；校验包头与 ELF（可执行与链接格式）架构。
  默认部署/rootfs 仅消费 runtime 包，并核对报告的发行版与 ABI（应用二进制接口）；
  schema 3 报告中的 development 包同样参与完整性检查。
- 服务遵循所选 init 的 systemd/OpenRC 声明；auto_start 控制安装/升级启用，false 不撤销用户启用。
  run 显式启动服务，运行入口与调试 PID 必须对应实际安装程序。
- 构建参数是组件名，刷写参数是清单分区名。写入前校验摘要、完整清单、分区几何和设备身份；
  SPI NAND 不制作可整片 dd 的 raw.img。
- Recovery 数据走 adb forward 与设备 loopback TCP，控制走 adb shell 单行 ASCII 协议，
  不依赖 adb exec:/shell:v2；受保护写入保留 host 确认、设备摘要和大小检查。

## 5. 编码与安全

- 简洁、明确、最小惊讶；错误必须传播或解释，资源有释放路径，不做无消费者的抽象。
- Python 最低 3.12，PEP 8，4 空格，行宽 100，使用类型注解，依赖由 pyproject.toml 管理。
  模块/函数/变量 snake_case，类 PascalCase，常量 UPPER_SNAKE_CASE。
- Bash 可执行脚本用 #!/bin/bash、可执行位、set -xeuo pipefail（包含 set -xe 约定）。
  被 source 的环境入口保留调用者选项，不主动启用 xtrace。路径变量双引号，临时文件用 mktemp/trap，
  不滥用 eval；4 空格缩进、局部变量用 local、函数用 function_name() { 格式。
- Makefile recipe 使用 Tab，工具链由环境传入，不硬编码宿主 gcc 或目标架构。
- 内核 C/C++ 遵循 Linux Kernel Coding Style（Tab 8）；用户态同模块统一 4 空格、行宽 100。
  函数/变量 snake_case、宏大写、头文件自包含；资源错误路径完整，避免无界动态分配。
- 不提交密钥、token（访问令牌）、私人口令或私有下载凭据；敏感配置走环境或忽略文件。
  外部下载校验可信 SHA256，临时写入、校验后原子替换；禁止 curl | bash 安装方式。
- 第三方源码、固件、工具和许可证保持原归属，不用根目录 Apache License 覆盖，见[许可说明](docs/licensing.md)。

## 6. CLI、日志与视觉

- 参数解析、编排、呈现分离；支持 --json、--no-color、--no-interaction、--target、-C/--workspace。
  JSON stdout 只输出一份带 schema_version 的结果，诊断走 stderr，非交互不弹菜单。
- 退出码：0 成功、1 操作失败、2 参数/配置错误、130 取消；App/test 保留程序码，超时 124。
  脚本不解析中文状态文案。
- 使用统一 BuildOutput 和 builder/term.py，不直接 print/logging 竞争终端。显示真实目标、动作、
  已耗时、结果、日志和恢复命令，不虚构百分比、ETA（预计完成时间）或成功状态。
- NORMAL 紧凑，VERBOSE 展开工具原文，QUIET 保留摘要与失败原因；全部保存完整日志。
  持有目标锁后轮转 build.log，默认 3 份历史，FLANGE_LOG_KEEP 调整。
- 颜色按语义：进行中蓝、成功绿、警告/取消黄、失败红、路径/命令青，正文默认色。
  stdout/stderr 分别检测；非 TTY、TERM=dumb、NO_COLOR 或禁色时降级，日志与 JSON 无 ANSI。
- 使用单调时钟；主异常绑定失败命令，清理错误附加报告；Docker 内外不重复根因。
  重试提示保留原请求，不默认建议 clean/force。
- 产品界面沿用组件实际视觉体系，字体、间距、层次和状态一致，不仅靠颜色表达。
  Nothing 风格仅在明确要求时采用，以黑白、清晰排版、少量状态色和真实数据为主。
  不保留与产品无关的品牌模仿规范或 Agent 提示词文件。

## 7. 验证与提交

- 测试保护当前可观察行为、边界和真实故障回归；删除旧设计快照、迁移完成断言、重复覆盖
  与只检查源码措辞/继承结构的用例。删除前确认对应行为仍有有效覆盖；不因失败而删除测试。
  预期集合非空时先确认其内容，避免空循环通过；外部依赖可隔离，仓库必需资源缺失应失败。
  修改有效但陈旧的断言时，按当前契约验证实际输出，不锁死无关版本号、私有调用序列和实现形式。
- 优先运行相关检查；涉及配置、构建、CI 或公共边界时运行完整 python -m pytest。
  编译验证通过 Docker，实机操作单独记录，不把 skipped、模拟测试或计划输出写成硬件通过。
- 文档检查链接、锚点、目标与 CLI 示例，并运行 git diff --check；不要求无关固件重编。
  删除流程时同步移除其命令、CI 与专属治理测试，保留功能测试。
- main 保持可构建。Agent 新分支默认 codex/<主题>，人工可用 dev/*、fix/*、release/*。
  每个提交一个目的，格式为 <类型>(<范围>): <中文简述>；类型可用 feat/fix/docs/refactor/build/ci/test/chore。
- 不提交 .build/、.flange/、临时检查报告和本地状态；大型二进制沿用 Git LFS（大文件存储）。
- 提交说明写问题、最终行为、验证和真实限制，不复述实施流水账，不附带未授权的其他修改。
