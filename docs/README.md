# flange 文档导航

第一次接触 flange，请从[第一次使用](first-steps.md)开始。
它先解释电脑、Docker、系统镜像与开发板的关系，再带你完成无需设备的构建计划，
随后选择 App 编译或整套系统构建。查参数可随时运行 `flange <命令> --help`。

## 按你的任务阅读

| 学习路径 | 先读 | 然后读 | 完成后的判断 |
| --- | --- | --- | --- |
| 初次使用 | [第一次使用](first-steps.md) | [开发指南](development-guide.md) | 能说明所选目标，找到计划与产物路径 |
| 构建、刷写、使用开发板 | [开发指南 §1–4](development-guide.md#1-准备宿主机与仓库) | [对应板卡](../wiki/boards/index.md) | 构建成功，并单独记录设备启动与功能验证 |
| 开发自己的应用 | [第一个 App](first-steps.md#第二步在-docker-中编译第一个-app) | [开发指南 §5–7](development-guide.md#5-在仓库外创建和构建-app) | 生成软件包；有设备时完成部署、运行与测试 |
| 维护已有项目 | [维护指南](maintenance-guide.md) | [架构职责参考](build-system-design.md) | 找到问题所属层，保存复现与验证证据 |
| 增加软件或硬件支持 | [扩展指南](extension-guide.md) | [项目规格](../ProjectSpec.md) | 在合适层修改，完成对应配置、构建与设备验证 |
| 参与仓库贡献 | [贡献指南](../CONTRIBUTING.md) | [项目规格](../ProjectSpec.md) | 变更有清晰范围、文档和验证记录 |

## 按问题查参考

| 你遇到的问题 | 文档 |
| --- | --- |
| 这个命令怎么用，构建失败去哪里看 | [开发指南](development-guide.md) |
| 代码从命令走到构建和设备的过程是什么 | [架构职责参考](build-system-design.md) |
| App 的配置字段、安装与运行约定是什么 | [App 参考](app-architecture.md) |
| 如何接入 CPack、拆分运行/开发包或扩展打包格式 | [包格式后端](package-backends.md) |
| 如何把一个硬件功能组合成 Package（功能包） | [硬件特性包](../wiki/concepts/硬件特性包.md) |
| 如何备份、恢复或在线刷写分区 | [Recovery（维护系统）](recovery.md) |
| 如何开发同一芯片上的异构从核 | [AMP（非对称多处理）](amp.md) |
| 这块板或外设验证过哪些功能 | [板卡索引](../wiki/boards/index.md)、[Wiki](../wiki/index.md) |
| Arduino UNO Q 如何构建、刷写及验收 | [UNO Q 适配指南](boards/arduino-uno-q.md) |
| 哪些能力仍有缺口，哪些结果已验证 | [构建系统设计评审](build-system-review.md)、[CLI 体验评审](cli-experience-review.md) |
| 代码、固件和生成镜像如何遵守许可证 | [许可说明](licensing.md) |

## 哪些文档代表当前约定

- [项目规格](../ProjectSpec.md)规定项目约束，[能力规格](../openspec/specs/)记录功能契约。
- 本目录的操作指南说明当前用法；板卡页说明具体硬件的适配与验证范围。
- 设计评审区分已验证事实、已知问题和下一步工作；待办事项不表示功能已经可用。
- `refactor-roadmap.md`、`python-build-system-design.html`、`superpowers/` 与 `proposal/`
  保留历史设计和实验背景。阅读实现细节时核对当前规格、源码和 CLI 帮助。

发现文档与命令不一致时，记录目标、命令与输出，按[贡献指南](../CONTRIBUTING.md)反馈。
