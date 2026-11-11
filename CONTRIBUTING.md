# 参与 flange 开发

提交可复现的问题、板卡验证结果或改进即可参与开发。
工程、文档和 AI Agent 规则统一以 [AGENTS.md](AGENTS.md) 为准。
首次使用读[入门教程](docs/first-steps.md)，修复问题读[维护指南](docs/maintenance-guide.md)，
添加软件或硬件读[扩展指南](docs/extension-guide.md)。

## 开发与验证

```bash
source envsetup.sh
python -m pytest
```

初始化会准备 Python 虚拟环境及开发依赖。单元测试在宿主运行；目标代码编译与系统镜像制作
通过 `flange` 在 Docker 内执行，设备验证需要对应硬件。具体检查范围见 [AGENTS.md](AGENTS.md#7-验证与提交)。

提交改进时说明具体问题、修改后的行为及验证结果；附上相关目标与复现命令。
同步受影响的结果文档和导航，清除被替代的描述。Pull Request（合并请求）中分别说明
单元测试、构建、刷写和实机功能的验证范围，便于维护者判断影响。

## 报告问题

请在 [GitHub Issues](https://github.com/flange-build/flange/issues) 中提供：

- flange commit、完整 `<board>-<product>-<variant>`、工作区扩展层和构建组件。
- 宿主系统、CPU 架构、Python / Docker / Compose 版本。
- 最小复现命令、预期行为、实际输出，以及构建日志中相关错误。
- 设备问题补充板卡硬件版本、存储介质、连接方式和串口日志。

分享日志前移除密码、token（访问令牌）、私钥及私有下载凭据。
涉及第三方内容时，请同时确认其[许可与再分发条件](docs/licensing.md)。
