## 1. 更新 ProjectSpec.md 目录结构

- [x] 1.1 将 ProjectSpec.md 第 9 节目录结构中的 `uboot/` 改为 `bootloader/`，并更新注释说明
- [x] 1.2 在 kernel/、bootloader/、image/ 目录下添加平台子目录结构示例（rockchip/、allwinner/、qualcomm/）
- [x] 1.3 在 board/ 目录结构中添加 `patches/kernel/` 和 `patches/bootloader/` 子目录示例
- [x] 1.4 更新 ProjectSpec.md 第 6.4 节构建与刷写目标约定中 `//uboot` 相关引用为 `//bootloader`

## 2. 更新 build-system-design.md 组件结构

- [x] 2.1 更新第 5.2 节组件 target 结构表格，将 `//uboot` 改为 `//bootloader`，补充平台子目录路由说明
- [x] 2.2 更新第 7 节目录结构，展开 kernel/、bootloader/、image/ 的平台子目录，添加 board 下的 patches 子目录
- [x] 2.3 更新第 5.3 节配置到构建数据流图，反映三层职责分离（platform → 配置，组件/平台 → 实现，board → 特化）
- [x] 2.4 更新第 2 节 CLI 中 `flange build uboot` 相关引用为 `flange build bootloader`

## 3. 更新 CLAUDE.md 引用

- [x] 3.1 检查 CLAUDE.md 中所有 `uboot` 引用，更新为 `bootloader`

## 4. 更新产物目录与 Docker 映射相关描述

- [x] 4.1 更新 build-system-design.md 8.8 节，移除"手动创建宿主机链接"方案，改为 Docker volume 实际目录映射，明确 `output/`（构建中间产物）和 `target/`（最终产物）均为实际目录，禁止符号链接
- [x] 4.2 更新 build-system-design.md 第 7 节目录结构中 output/ 和 target/ 的注释，移除链接相关说明

## 5. 添加补丁归属与新增平台规范

- [x] 5.1 在 build-system-design.md 中添加补丁归属判断规则章节：平台通用补丁放组件平台子目录，板级补丁放 board 目录
- [x] 5.2 在 build-system-design.md 中添加新增平台 checklist：需要在 kernel/、bootloader/、image/ 各建子目录，并在顶层 BUILD.bazel 的 select() 中各加一行
