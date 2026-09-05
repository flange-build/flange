# 文档品牌资源

- `flange-logo-readme.png`：2026-09-05 为 GitHub README 设计的 Logo，深墨色字标与青绿色连接图形，
  表达 flange 连接源码与设备的角色。由 imagegen 生成，保存在仓库内，白底适配 GitHub 明暗主题。
- `flange-logo.svg`、`flange-logo.png`：既有品牌资源，保留供历史材料使用。
- `terminal-colors.png`：2026-09-05 从临时工作区的真实 PTY（伪终端）输出生成的语义颜色预览，
  对照深浅背景；展示 source 就绪、工作区状态、目标列举与选择、无效参数反馈。
  色值是预览主题，实际颜色由用户终端决定。记录命令未编译或操作设备。
- `build-log.png`：2026-09-05 当前 Khadas `build app` 的实际 PTY（伪终端）记录，经终端文本回放页截图保存。
  adbd、flange-rootfs-grow、recoveryctl 均复用通过核验的产物，App 汇总阶段约 0.6 秒完成。
  该图只展示 App 阶段日志，不证明完整系统镜像或设备验证通过；原始终端记录本次保存在
  `/tmp/flange-build-log-preview/after.ansi`。实际色值由终端主题决定。

README 使用带替代文本和显式宽度的相对图片路径；不依赖外部图床。资源随项目整体许可状态管理。
