# Linux upgrade_tool

本目录收录 Khadas 官方工具仓库分发的 Rockchip `upgrade_tool v2.44`，用于
`flange flash` 的 Rockchip 宿主刷写。二进制为 x86_64 静态 ELF，不包含 Linux ARM64 版本。
安装、检查命令与验证范围见 [Rockchip 宿主工具说明](../../../docs/platforms/rockchip.md#宿主-upgrade_tool)。

[manifest.json](manifest.json) 固定上游提交、逐文件下载地址、Git blob（文件对象）摘要与
SHA256。下载后已核对 Khadas 官方 Git 对象；SHA256 为核对后在本地计算的记录，
不是厂商单独发布的签名或摘要清单。

二进制、配置、修订记录与 PDF 保持上游内容；PDF 沿用仓库原有中文文件名，
上游名为 `linux-upgrade-tool-user-guide.pdf`。配置项均为注释，不预设刷写策略。
可执行文件由 Git LFS（大文件存储）管理，需完成 `git lfs pull` 后使用。

这些文件为 Rockchip 第三方材料，不适用 flange 的 Apache-2.0。
该工具目录未随附独立 LICENSE，保留原始 PDF 与修订记录，不推定其为开源软件；
参见[许可说明](../../../docs/licensing.md)。
