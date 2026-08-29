## 1. 多 DEB App 契约

- [x] 1.1 为 AppSpec 增加安全的 `build.deb_outputs` 解析与约束测试
- [x] 1.2 为 AppBuilder 注入标准构建路径环境并交付多个已构建 DEB
- [x] 1.3 增加多 DEB 成功、缺失输出和既有单包兼容测试

## 2. Rockchip 多媒体 package

- [x] 2.1 创建 package 清单、构建 App、udev 配置 App 与中文 README
- [x] 2.2 迁移并核对 GStreamer core/base/good/bad 的 83 个 Rockchip 补丁
- [x] 2.3 实现 MPP、RGA、GStreamer 与 Rockchip plugin 的交叉构建和 staging
- [x] 2.4 实现 Noble 模板重打、厂商 runtime 打包、root 所有权与未映射文件检查
- [x] 2.5 增加 DEB metadata、版本、分包和 WebRTC 静态检查

## 3. 配置迁移

- [x] 3.1 删除 `common.multimediaDebs` 及各 SoC 的远程 `extra_debs` 引用
- [x] 3.2 为现有受支持 RK35xx board 显式启用 `rockchip-multimedia`
- [x] 3.3 增加全量板级配置解析与旧 URL/hold 消失测试

## 4. 验证与文档

- [x] 4.1 运行 App/package/config 单元测试与 OpenSpec strict validate
- [x] 4.2 在 flange Docker 内完成多媒体 DEB 构建并检查 `dpkg-deb` metadata、所有权和 WebRTC 文件
- [x] 4.3 记录未执行的目标板 rootfs/实机验证命令与结果边界
