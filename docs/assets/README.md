# 文档品牌与架构资源

- `flange-logo.png`：2026-09-06 确定的正式 Logo，采用 C2「石墨 × 橙」方向。
  三层模块与 `f` 负形表达组件组合，搭配小写 flange 字标。由内置 imagegen 基于 C 方案润色生成，
  使用浅色不透明背景。当前为 PNG（位图），尚无正式矢量源文件；其他候选及旧版 Logo 已移除。
- `architecture/flange-layers.svg`：分层设计图，展示仓库分工、扩展层组合与配置求值顺序。
- `architecture/flange-architecture.svg`：构建部署架构图，展示宿主机、Docker、工作区产物和设备边界。
  两图使用可编辑 SVG（可缩放矢量图），石墨与橙色配色，中文标签；事实来源为
  [项目规格](../../ProjectSpec.md)、[多层工作区](../layers.md)和[架构设计](../build-system-design.md)。
  README 使用图片嵌入并链接原图，可点击放大。
- `terminal-colors.png`：2026-09-05 从临时工作区的真实 PTY（伪终端）输出生成的语义颜色预览，
  对照深浅背景；展示 source 就绪、工作区状态、目标列举与选择、无效参数反馈。
  色值是预览主题，实际颜色由用户终端决定。记录命令未编译或操作设备。
- `build-log.png`：2026-09-05 当前 Khadas `build app` 的实际 PTY（伪终端）记录，经终端文本回放页截图保存。
  adbd、flange-rootfs-grow、recoveryctl 均复用通过核验的产物，App 汇总阶段约 0.6 秒完成。
  该图只展示 App 阶段日志，不证明完整系统镜像或设备验证通过；原始终端记录本次保存在
  `/tmp/flange-build-log-preview/after.ansi`。实际色值由终端主题决定。

README 使用带替代文本和显式宽度的相对图片路径；不依赖外部图床。资源随项目整体许可状态管理。
