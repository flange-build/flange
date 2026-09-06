# 参与 flange 开发

感谢提交可复现的问题、板卡验证记录和改进。项目约束以 [ProjectSpec](ProjectSpec.md) 为准；
首次使用请阅读[入门指南](docs/first-steps.md)，第一次修问题读[维护指南](docs/maintenance-guide.md)，
增加 App、产品或板卡读[扩展指南](docs/extension-guide.md)。[架构说明](docs/build-system-design.md)用于查模块职责。

## 开发环境与检查

```bash
source envsetup.sh
python -m pytest
npx --yes @fission-ai/openspec@1.2.0 validate --all --strict
```

OpenSpec 是维护规格使用的独立工具，来源为 [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec)。
它的 npm 包名是 `@fission-ai/openspec`，不是 `openspec`；安装步骤见开发指南。
目标代码编译与镜像制作通过 `flange` 在 Docker 内执行，pytest 在宿主 Python 环境运行。
单元测试、命令模拟测试和实机验证请分别报告，不以某一层替代其他层。

## 提交一个改进

1. 先说明问题、具体触发条件和预期结果；架构问题可参考[设计评审](docs/build-system-review.md)。
2. 通过 OpenSpec 探索、提案、实施和归档流程管理功能及规范变更，每个任务不超过两小时。
3. 保持单一目的：平台策略放在 `builder/platforms/`，硬件内容放在 `components/`，路径遵循 `builder/paths.py` 与 `WorkspaceContext`，运行选项不混入系统配置。
4. 完成受影响检查，记录工作区、target、计划/产物/会话结果和实机验收范围；改变既有行为时解释原因。
5. 同步 README / 开发指南 / ProjectSpec / 对应能力 spec。历史记录保留历史语境，当前入口不得继续描述旧行为。
6. 提交 Pull Request（合并请求），描述问题、最终行为和验证证据。所有文档、注释和 commit message 使用中文。

OpenSpec 不要求先会使用某个 AI 工具。安装 Node.js/npm 后，可以从工具 checkout 运行：

```bash
# 把示例名替换为这次改动的简短名称
npx --yes @fission-ai/openspec@1.2.0 new change explain-config-error
npx --yes @fission-ai/openspec@1.2.0 status --change explain-config-error
```

按生成的工作流补齐 `proposal.md`（为什么改）、`design.md`（怎样改）、`specs/`（哪些契约改变）
和 `tasks.md`（怎样实施和验证）。用 `instructions <artifact> --change <name>` 查看对应模板；
修改代码与文档后完成检查，再执行 `archive <name>` 同步主规格并归档。
这些是 OpenSpec 的子命令；`flange` 的命令负责构建和设备流程。

## 修改文档

- 教程写明在哪里运行、前置条件、成功标志和下一步；不要把模拟输出描述为实机结果。
- README 负责起点；入门页负责教学；操作参考负责完整参数；维护/扩展页解释修改路径。
- 图示使用 GitHub 支持的 Mermaid 或仓库内图片，同时提供文字说明，主要导航使用标准 Markdown 链接。
- 更新命令或字段时，用当前 CLI 和解析器核对示例；检查本地链接和图示是否可读。
- 历史材料保留日期和用途，不能作为当前能力的唯一说明。

## 报告问题

请在 [GitHub Issues](https://github.com/flange-build/flange/issues) 中提供：

- flange commit、完整 `<board>-<product>-<variant>` 与构建组件。
- 宿主系统、CPU 架构、Python / Docker / Compose 版本。
- 最小复现命令、预期结果、实际输出及 `build.log` 中相关错误。
- 若涉及设备，补充板卡版本、存储介质、连接方式和启动串口日志。

分享配置或日志前移除密码、token（访问令牌）、私钥和私有下载凭据。
不要提交 `.build/`、`.flange/`、外部 App 构建目录或运行时数据。

新增字段须同时具备严格 schema、消费者、计划输入及错误用例；新增命令须验证帮助、非交互、JSON 与退出码。
