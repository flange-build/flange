# 新人文档验证记录

日期：2026-09-05。

## 试读方法与发现

`newcomer_docs` 以不继承项目对话背景的独立子 agent 启动，从 README 与当前仓库文件开始学习。
这是新人视角的模拟试读，不是真人用户测试。它负责 README、文档导航与第一次使用教程；
另一个独立子 agent 核对 Wiki，主 agent 编写维护、扩展指南并交叉检查实现。

首次试读发现：原入口默认读者理解目标命名、系统镜像和 Docker 镜像的区别，缺少无需设备即可完成的
第一步；外部工作区与工具 checkout 的关系不够直观，维护和扩展缺少从任务到源码的入口。
据此形成“查看计划 → 编译第一个 App → 为自己的板卡构建系统”的学习顺序，并加入前提、运行位置、
成功判断与下一步。

第二次独立复读发现并修复了五个具体断点：

1. 构建示例后的清理命令会移除即将刷写的产物：明确清理为可选，并提示继续刷写时跳过。
2. 从外部工作区进入 Package 或测试章节时目录不明确：补充工作区与工具根的切换命令。
3. `--target` 的临时产品选择没有带到后续构建：后续构建和刷写查看命令显式使用同一目标。
4. 独立 App 编译后加入系统的配置缺失：补充 `rootfs.custom_packages` 追加片段及工作区来源条件。
5. App 源码入口只写了目录：明确示例文件 `apps/sensor-agent/src/main.c`。

Wiki 交叉审查同时修正旧构建 API、缓存与产物路径、脚手架行为、外部 App 装载、systemd 安装行为、
内核启动路径及 Recovery 启用条件。adbd 页面改为引用当前二进制 README 的版本和验证范围，保留
带日期的历史实验记录。ProjectSpec 不再把已替换的 android-tools-4.2.2 写成当前版本，既有 Recovery
传输协议约束保持明确。

## 命令与配置

在临时外部工作区通过当前 `python -m builder` 入口实际执行了 9 条文档命令：
初始化、目标选择、目标查看、镜像计划、状态查看、创建 App、App 计划、创建 Package、Package 计划。
目标使用 `radxa-zero3w-default-debug`；计划结束后没有生成 `.build` 或伪装成已编译产物。

从扩展指南提取完整 Jsonnet 示例，放入隔离的工具配置树，通过当前 Jsonnet 求值与严格配置解析验证：

- `default`、`desktop`、`demo` × `debug`、`release` 共 6 个组合均可解析；
- 新产品出现在有效目标列表中，demo hostname 正确，已有产品的软件包及用户配置保留；
- Package 示例中的 vendor App 正确进入 rootfs 选择与本地来源；
- 独立 App 的配置片段能追加选择，`WorkspaceContext` 与 `AppResolver` 能解析到实际工作区源码。

这些检查验证命令及配置语义，不代表已编译系统镜像或完成设备验收。

## 文档与图示

- 检查 README、ProjectSpec、CONTRIBUTING、docs 顶层指南及全部 Wiki，共 115 份 Markdown 文档；
  642 个本地 Markdown/HTML 链接及标题锚点均有效。代码示例中的伪链接不作为实际导航检查。
- 94 份带 frontmatter（页首元数据）的 Wiki 页面解析成功，列出的本地源码引用全部存在。
- README、第一次使用、维护指南、扩展指南及架构参考中的 8 张 Mermaid 图使用官方 Mermaid CLI
  和 Chrome 实际渲染，人工检查结果；扩展选择图改成横向分支，避免五列并排导致标签过密。
- 核心导航使用 GitHub 可直接跳转的标准 Markdown 链接；Wiki 的历史关联元数据仍可保留双括号形式。
- `git diff --check` 通过。

## 仓库检查

- 全量 pytest：**1694 passed，7 skipped**，耗时 233.15 秒。
- 归档前 `openspec validate --all --strict`：**78 passed，0 failed**。
- 归档同步 `developer-documentation`：修改 2 条要求、增加 2 条要求，明确工作区归属与新人文档契约。
- 归档后 `openspec validate --all --strict`：**77 passed，0 failed**。
- 归档后 `pytest tests/openspec -q`：**134 passed**；链接检查与 `git diff --check` 再次通过。

本次仅调整文档，未执行真实系统编译、部署或刷写。7 项 opt-in（显式启用）Docker 集成测试在本次全量
测试中跳过；不将模拟试读、配置求值、单元测试或历史板卡记录表述为本次硬件验证。
