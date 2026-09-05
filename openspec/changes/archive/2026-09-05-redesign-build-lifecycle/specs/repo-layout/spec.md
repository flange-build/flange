## MODIFIED Requirements

### Requirement: 产物层职责边界

运行时派生物 MUST 位于 `WorkspaceContext.build_root`，默认是当前工作区的 `.build/`，允许在 `flange.toml` 中用 `build_dir` 指定其他目录。该根下 SHALL 以 `cache/` 保存共享缓存、`sources/` 保存共享下载、`work/<target.key>/` 保存目标中间目录、`target/<board>/<product>/<variant>/` 保存已发布产物、`locks/` 协调共享状态。工具仓库与外部工作区的产物 MUST NOT 因 cwd 变化而混写。

#### Scenario: 默认工作区派生目录
- **WHEN** 工作区没有覆盖 build_dir
- **THEN** 缓存、下载、中间目录和产物统一进入该工作区 `.build/`，且默认 `.build/` 不进入版本控制

#### Scenario: 独立构建存储
- **WHEN** 工作区配置了绝对 build_dir
- **THEN** 全部构建路径由该 build_root 推导，产物位于 `target/<board>/<product>/<variant>/`，工具仓库不会额外生成另一份输出

#### Scenario: 清理目标
- **WHEN** 开发者通过 CLI 清理当前目标
- **THEN** 清理在该目标锁内完成，不能修改工具内容层或用户本地源码；需要的派生物可由后续构建重新创建

### Requirement: 跨层引用方向

运行时路径 MUST 由显式 `WorkspaceContext` 提供。工具内容使用 `context.components_root`，目标产物使用 `context.target_dir`，下载和工作目录使用 `context.sources_dir` 与 `context.build_root`；不得用 cwd、仓库全局 BUILD_ROOT 或根级软链接猜测当前工作区产物位置。`builder.paths` MAY 提供已安装工具根的默认发现入口，不承担当前工作区和目标状态。

#### Scenario: 从外部工作区启动构建
- **WHEN** 调用者 cwd 不在 flange 工具仓库中
- **THEN** 平台内容仍从 tool_root 读取，所有产物写入所选 workspace/build_root 的当前目标目录

#### Scenario: 宿主与容器路径
- **WHEN** 工作区资源传入构建容器
- **THEN** 工具、工作区、build_root 和外部 App 挂载到相同绝对路径，计划和 manifest 不需要 `/workspace` 路径翻译

## REMOVED Requirements

### Requirement: target 便捷软链接
**Reason**: 工作区和构建目录已经可以独立于工具仓库；根级 target 软链接无法代表当前目标。
**Migration**: 使用 `flange status` 或结构化计划查询实际 target_dir；envsetup.sh 只引导 Python 环境，不创建业务目录软链接。
