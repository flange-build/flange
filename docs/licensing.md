# 许可说明

flange 自有代码与文档采用 [Apache License 2.0](../LICENSE)，SPDX（软件包数据交换）标识为 `Apache-2.0`。
根目录保存 [Apache 官方许可原文](https://www.apache.org/licenses/LICENSE-2.0.txt)，保持英文以便工具识别和原文引用。
构建产物中的各个组件仍按各自许可证分发。

## 适用范围

- flange 原创的构建框架、配置、文档和品牌资源默认适用根目录 Apache-2.0；文件内另有许可声明时按该声明处理。
- 第三方源码、固件、二进制工具和随附许可证保留上游许可，不因被本仓库收录而改为 Apache-2.0。
- 对第三方项目的补丁沿用对应上游许可，不使用根目录 Apache-2.0 覆盖已有权利声明。
- 通过 flange 生成的镜像包含 Ubuntu、Linux、U-Boot、App 和固件等独立组件，各组件许可分别适用。

## 维护约定

引入第三方内容时记录上游来源、版本或 commit、许可证及随附版权信息。
发布镜像前，应核对实际包含的软件包与固件，保留需要随分发交付的许可、版权和对应源码材料。
当前框架导出部分包版本信息，但尚未自动生成完整 SBOM（软件物料清单）、许可清单或对应源码归档；
这些属于[设计评审](build-system-review.md)中的后续发布能力。

仓库中已有独立声明的例子包括 `components/amp/rockchip/rt-thread/`、
`components/amp/rockchip/hal/` 和 `tools/*/edl-ng/`。这不是完整第三方清单，
根目录 LICENSE 的加入也不代表已完成全仓第三方材料审计。
