# firmware-qcom-audioreach

本 package 只参考 Radxa 上游 deb 的内容，携带 Dragon Q8B 所需的 AudioReach
topology 数据。flange 通过本目录的 `app.yaml` 重新生成无上游发行版依赖的 deb，
再由 rootfs 的统一 `dpkg` 流程安装；不会直接安装 Radxa 的 deb 或执行其
maintainer script。

- 来源：`radxa-pkg/audioreach-topology` release `1.0.4-2`
- 来源 deb SHA-256：`721a8c69996cc60c9fe2dc593faf2e7e5de99905f80da1739a284d97e5ada88d`
- 提取文件：`qcom/sc8280xp/radxa/dragon-q8b/SC8280XP-Radxa-Dragon-Q8B-tplg.bin`
- 文件 SHA-256：`737787a3b6a52ff9b66e1f5208e98c6491180130ffbff4a770c40cca34f63ee6`
- flange deb：`firmware-qcom-audioreach_1.0.4-2_arm64.deb`
- 安装路径：`/lib/firmware/qcom/sc8280xp/SC8280XP-Radxa-Dragon-Q8B-tplg.bin`

上游 Q8B topology 源文件标注 `SPDX-License-Identifier: BSD-3-Clause`。
