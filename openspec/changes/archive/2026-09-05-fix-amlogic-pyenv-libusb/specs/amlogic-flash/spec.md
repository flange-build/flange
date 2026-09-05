## ADDED Requirements

### Requirement: macOS pyenv 刷写入口 SHALL 解析为真实脚本

macOS 的 Amlogic 刷写在 PATH 命中 pyenv shim 时 SHALL 按当前 pyenv 环境解析真实可执行入口，再传递动态库搜索路径并启动；MUST NOT 在设置 DYLD 环境后执行该 Shell shim。入口无法解析时 MUST 在设备传输前报告可操作错误。

#### Scenario: pyenv 安装的 pyamlboot

- **WHEN** boot-g12.py 来自当前 pyenv root 的 shims 目录
- **THEN** 使用 pyenv which 返回的真实入口执行 USB 引导，保留 Homebrew libusb 搜索环境

#### Scenario: 普通安装入口

- **WHEN** PATH 命中普通 boot-g12.py 脚本
- **THEN** 不要求额外查询或安装 pyenv

#### Scenario: 解析失败

- **WHEN** pyenv 不可用、解析超时或返回无效入口
- **THEN** 在设备等待或写入前返回明确错误，不继续执行 shim
