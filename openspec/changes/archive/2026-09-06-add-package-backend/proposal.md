## Why

App 构建层直接包含 DEB 命名、生成、验证和运行包选择，现有 custom vendor 多包全部进入运行环境且不提供完整依赖安装树。CPack 组件拆包需要明确的运行/开发角色，以及可替换格式的包管理后端。

## What Changes

- 新增 `packaging.format` 与 `packaging.outputs[].file/role`，精确声明完整外部包，兼容 `build.deb_outputs`。
- 提取包后端接口和 DEB 实现，负责格式命名、默认打包、外部包验证与提取、设备安装命令；APT 编译依赖归入 Ubuntu 构建环境适配。
- 构建与发布使用带格式和角色的包记录；所有包还原到依赖安装树，默认 rootfs/部署仅消费 runtime。
- CLI 同时展示运行包与开发包，增加边界测试和可联调文档。

## Capabilities

### New Capabilities

- `package-backends`：格式后端、角色化产物与扩展边界。

### Modified Capabilities

- `python-app-packaging`：外部多包解析、兼容入口、安装树和准确发布契约。

## Impact

AppSpec、AppBuilder、AppBuildReport、设备部署、Ubuntu rootfs 消费、CLI、测试和开发文档。仅实现 DEB；报告结构升级会要求旧报告重新构建。

## 非目标

不实现 RPM/APK，不修改 heaven-media-searchd 业务或 RPC、不代替 CPack 管理组件内容或维护脚本、不部署设备。
