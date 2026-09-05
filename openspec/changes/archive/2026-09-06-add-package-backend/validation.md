# 验证记录

## 实现范围

- `packaging.format/outputs` 精确声明多个完整包及 runtime/development 角色，旧 `build.deb_outputs` 规范化为 runtime。
- DEB 后端承担默认拆包、外部包架构校验与安装树合并、设备安装命令；APT 编译依赖由 Ubuntu 适配器负责。
- 所有包写入 schema 2 报告与产物清单；开发文件参与下游编译，设备和 Ubuntu rootfs 默认只安装运行包。
- 包缺失、路径冲突、运行入口不属于 runtime、架构错误和内容篡改阻止成功发布；上次成功产物保留。
- 后端配方参与缓存身份，排除宿主与容器生成的 `__pycache__`，避免字节码导致误重建或中途输入变化。
- README、开发指南、App 架构、系统架构、ProjectSpec 和 CPack 图文接入指南同步。

## 已执行检查

- 最终完整检查：`python -m pytest -q`，1895 项通过、14 项按环境条件跳过，耗时 203.91 秒；
  Docker CPack 集成测试单独显式启用，结果见下文。
- 初次相关回归：421 项通过，覆盖 App 配置/构建/部署、DEB、rootfs/recovery、CLI 输出及严格配置边界。
- 补充边界检查：`python -m pytest tests/builder/test_package_backend.py -q`，33 项通过。
  包括真实 DEB 数据夹具、默认库拆包、完整包字节保留、下游开发文件、运行包过滤、旧入口导入与旧报告拒绝。
- Docker CPack 集成：实际交叉编译 ARM64 服务和静态 SDK，生成两个 DEB，通过 Flange 导入后，
  下游 CMake 工程使用 `find_package` 与导出 target 完成链接；验证缓存复用与删除开发包后的重建。
  初次运行 1 项通过，耗时 24.04 秒；修复字节码缓存输入后再次运行通过，耗时 22.54 秒。
- `openspec validate --all --strict`：79 项通过、0 项失败，增量规格已同步并归档。
- 新增 Python 模块与测试通过 Ruff 静态检查及格式检查；`git diff --check` 通过。
- 两份文档的完整 app.yaml 示例通过实际解析，修改文档中的本地文件链接检查通过。

## 工程协作与边界

已向 heaven-media-searchd 协作任务提供并确认 `packaging.outputs[].file/role`、`systemd.unit`、
维护脚本归属和报告契约。该工程运行包及含静态 RPC 库的开发包采用真实 `arm64` 架构；
纯头文件包仍可按元数据使用 `all`。实际业务工程的构建和验收由该任务记录，本记录不把夹具验证等同于业务验收。

本次不连接设备、不部署软件，不实现 RPM/APK 或宿主开发包安装命令。
