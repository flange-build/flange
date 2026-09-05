## ADDED Requirements

### Requirement: fastboot 写入前 SHALL 完成有界就绪握手

Amlogic 的 `pre_flash` SHALL 在 30 秒总时限内完成 USB 枚举及只读 `getvar version` 握手，每个探测子进程最多等待 5 秒且不得超出剩余总时限。新上传 U-Boot 和复用已有 fastboot 设备 SHALL 经过相同检查，`--no-wait` MUST NOT 跳过该检查。只有唯一设备成功返回版本响应后，GPT、分区和重启命令才 SHALL 被允许，并通过 `-s` 绑定该序列号。

#### Scenario: USB 模式切换延迟或首次握手无响应
- **WHEN** pyamlboot 已结束，但设备尚未枚举或首次只读握手超时
- **THEN** 系统回收超时的探测进程，在剩余时限内通过新进程重试只读探测
- **AND** 握手成功后才执行一次 GPT 写入

#### Scenario: 已在 fastboot 模式
- **WHEN** 初始检测识别到 fastboot 设备
- **THEN** 系统跳过 pyamlboot 上传，但仍验证只读握手后再写入

#### Scenario: 未就绪或设备不唯一
- **WHEN** 总时限内没有成功的版本响应，或枚举到多台 fastboot 设备
- **THEN** 系统报告明确错误，MUST NOT 执行 GPT、分区或重启命令

### Requirement: GPT 写入 SHALL 有超时且不得自动重放

`fastboot oem format` SHALL 最多等待 30 秒。超时或失败时系统 MUST 停止后续分区写入，MUST NOT 自动重试这个持久写入命令；超时错误 SHALL 明确设备端执行结果未知，并提供检查连接和重新进入刷写模式的提示。

#### Scenario: GPT 命令无响应
- **WHEN** `oem format` 超过 30 秒未结束
- **THEN** 系统结束并回收宿主机命令进程，报告超时与结果未知
- **AND** 不重放 GPT、不写入后续分区、不重启设备
