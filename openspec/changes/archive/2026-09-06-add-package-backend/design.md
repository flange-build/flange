## Context

现有 AppBuilder 内嵌 DEB 文件名、DebBuilder、dpkg-deb 和 APT。lib 类型已有默认拆包，custom vendor 通过 `build.deb_outputs` 导入完整 DEB，但全部记作 runtime。依赖仅消费安装树，因此只有 DEB 没有 DESTDIR 的 CPack 工程不能提供头文件与库。

## Goals / Non-Goals

目标：保持完整包与安装树来源一致，角色与文件名独立，新增格式不修改通用构建流程。非目标：新包格式实现、业务工程修改或设备部署。

## Decisions

1. 顶层 `packaging: {format: deb, outputs: [{file: ..., role: runtime|development}]}` 表达交付物；构建方式仍由 build 决定。外部完整包不限制为 vendor，可用于 service/exec/lib/test。旧 deb_outputs 保持限制，规范化为全部 runtime，不能与新段混用。
2. `PackageBackend` 策略负责规划、默认打包、导入验证/提取及设备安装命令。DEB 实现复用 DebBuilder。Ubuntu 的 APT 编译依赖由独立环境适配器负责，因为构建环境包管理器和交付包格式不是同一选择。
3. AppBuildResult 使用格式、角色、路径组成的 PackageArtifact。报告升级为 schema 2；旧 runtime_debs 读取接口可作 DEB 兼容视图，但通用执行/呈现消费角色化包记录。包后端与模型代码进入配方身份。
4. 外部包内容是交付依据。DEB 后端逐包验证架构，在独立临时目录提取，拒绝安装路径冲突后合并到 install；runtime 入口必须来自 runtime 包。全部安装树进入下游依赖前缀，默认部署和 Ubuntu rootfs 只安装 runtime。包文件本身不重打包，不运行维护脚本。
5. 默认生成的 lib 包仍拆分 runtime/development；头文件、静态库、pkg-config、CMake 开发元数据及未带版本的共享库链接属于 development。
6. 外部完整包的新配置不接受另行声明 install/depends/conffiles/data_dirs/maintainer_scripts/lib 或 auto_start=true，避免设置被静默忽略；这些交付语义由外部打包器实现。systemd.unit 绑定生命周期，不替代 CPack 的 unit 和安装脚本。

## Risks / Trade-offs

- schema 升级使旧 `--no-build` 报告失效 → 明确提示重新 app build，默认构建配方自动失效重建。
- DEB 提取多包可能同路径内容冲突 → 拒绝不同节点/内容覆盖，失败保留上次成功发布。
- 未来包格式不能直接安装到 Ubuntu rootfs → Ubuntu 适配边界显式拒绝非 DEB，设备默认部署暂只接受单一格式闭包。

## Migration Plan

已有 deb_outputs 无需修改。CPack 工程迁移为 packaging.outputs，脚本仅交付声明的完整包，不再自行提取 DESTDIR；开发库声明 development。运行一次 app build 生成新版报告。
