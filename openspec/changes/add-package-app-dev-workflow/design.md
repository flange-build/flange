## Context

现有 App 开发入口由 `envsetup.sh` 的多个 verb-first 分支分别拼装 Python 调用，并在启动最外层 Docker
前丢失调用者 cwd 与仓库外源目录。Package 只有 board opt-in 展开逻辑，没有独立生命周期入口。两者已经有
可复用的 AppBuilder、DebBuilder、package 清单加载和 ADB 部署能力，因此本变更只补一层资源编排。

## Goals / Non-Goals

**Goals:**

- 在任意目录用一致的 noun-first 命令完成 App 与 Package 开发闭环。
- 标准 vendor App/Package 复用现有构建与部署流水线。
- 让不能从既有类型推断行为的资源以安全、显式的 argv action 接入。
- 修复仓库外 Docker 挂载、目标状态路径与标准模板 deb 收集的根因。

**Non-Goals:**

- 不创建通用任务图、插件系统或第二套 package 构建器。
- 不自动修改 board 配置、App registry 或刷写分区。
- 不为 Device Tree、内核驱动虚构 run/debug/log 语义。

## Decisions

### 1. CLI 使用薄 Python 编排层

`envsetup.sh` 只识别 `flange app` / `flange package` 并把原始 argv 与调用者 cwd 交给 Python 模块。
解析、路径校验和生命周期选择集中在该模块，旧 verb-first 入口继续保留。

备选方案是在 shell 中继续增加分支；这会复制路径转换和错误处理，并延续字符串插值风险，因此不采用。

### 2. 构建入口先在宿主机解析，再启动 Docker

资源路径在宿主机按调用者 cwd resolve。仓库内路径转换为 `/workspace/...`；仓库外路径以相同绝对路径
bind mount 到最外层构建容器。lunch state 固定从 project root 读取，产物仍写入统一 target 输出目录。

这样只增加一次必要挂载，编译与打包仍全部发生在 Docker 内。

### 3. Package 复用 component，例外使用 argv action

只有 vendor component 能自然复用 App/Deb 与 ADB 生命周期。Package 恰含一个 vendor 时可自动选择；多个
vendor 时 run/debug/log 要求 `--component`。其他类型若没有显式 action，命令以“不支持该生命周期”失败。
混合 Package 不静默跳过其他类型；只有显式 `--component` 选中 vendor 时才执行局部生命周期。

`PACKAGE["actions"]` 与 App `actions` 均为 action 名到 argv 数组的映射，不接受 shell 字符串。`build`
action 在构建容器执行，其他 action 在宿主机执行；`--` 后参数只追加到 argv，不经 shell 展开。CLI 向
action 提供 `FLANGE_SOURCE_DIR` 与 `FLANGE_TARGET_DIR`，action 负责把发布产物写入后者。

备选方案是为每种 component 发明 deploy/debug 行为；其中涉及分区刷写和内核状态，既不通用也不安全。

### 4. 标准 App 的默认运行时行为保持简单

deploy 继续安装 deb；exec/service 继续使用现有启动语义。log 对 service 使用目标机 `journalctl`；debug
仅在 debug variant 下通过 ADB 启动目标机 GDB（exec 使用 `--args`，service attach 当前 MainPID）。无法
推断的类型要求显式 action。

### 5. 安装 staging 是 deb 内容的唯一新增来源

CMake/Meson/Make 使用各自原生 install 命令写入 DESTDIR，Swift 复制已知 executable；staging 与现有
`install.files` 合并后交给 DebBuilder。模板已有 install 规则，因此不增加自定义产物描述格式。

## Risks / Trade-offs

- 外部 action 等同执行资源作者提供的程序；CLI 会显示即将执行的 argv，但其信任边界与现有
  `package.py` / custom build command 相同。
- GDB 直接占用 ADB 交互会话，适合最小本地调试闭环；需要 IDE remote protocol 时应由显式 debug action
  提供 gdbserver 集成。
- 多 vendor Package 不能无歧义地选择运行对象，因此要求 `--component`，增加一次显式输入以避免误操作。

## Migration Plan

1. 新增 noun-first 入口与兼容测试，旧命令不改语义。
2. 修正 state、挂载与 staging 后，用临时仓库外模板验证 create → build。
3. 文档示例逐步迁移到 noun-first；旧入口在独立变更中决定是否弃用。

若回滚，只需移除新入口和 action 字段；既有清单、旧命令与产物布局不受影响。

## Open Questions

- 暂无。IDE remote debugging、非 ADB transport 和分区级 package deploy 留给有明确设备契约的后续变更。
