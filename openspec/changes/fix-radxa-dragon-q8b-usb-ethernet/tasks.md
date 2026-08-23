## 1. Kernel 来源与板级 Device Tree

- [x] 1.1 Q8B kernel 改为跟踪 `radxa/kernel` `linux-7.0.11` 分支 HEAD
- [x] 1.2 板级 patch 将 `a600000.usb` 固定为 peripheral，`a800000.usb` 保持 host

## 2. 缓存与自动化验证

- [x] 2.1 浮动 named repo 绕过组件缓存，并将真实仓库 HEAD 纳入哈希
- [x] 2.2 扩展测试，验证浮动分支、named repo 哈希和固定 USB 角色 patch 作用域
- [x] 2.3 同步当前分支 HEAD，并执行 patch check

## 3. 质量检查

- [x] 3.1 运行相关 pytest、OpenSpec strict 校验与工作树检查

## 4. Kernel 构建裁剪

- [x] 4.1 使用 `kernel.disable_configs` 关闭 Q8B 明确不用的重型模块，不增加 config patch
- [x] 4.2 增加配置测试，确保 QPS615/TC956x、USB 网卡、DRM MSM 与 Wi-Fi 不在裁剪名单
- [x] 4.3 静态核对额外 config 裁剪列表与 Q8B 必需驱动保留项

## 5. 浮动分支增量编译

- [x] 5.1 HEAD 未变化时跳过 mixed reset，保留源码时间戳与 `.o` 缓存
- [x] 5.2 增加回归测试并执行相关 pytest、OpenSpec strict 与 diff check

## 6. HEAD 更新与编译缓存

- [x] 6.1 HEAD 更新时优先 hard reset，失败时保留 mixed reset 兼容回退
- [x] 6.2 Qualcomm 内核接入项目目录下的持久化 ccache
- [x] 6.3 增加回归检查并执行相关 pytest、Compose 配置校验、OpenSpec strict 与 diff check

## 7. Q8B DWC3 gadget 稳定性

- [x] 7.1 Q8B 复用现有 DWC3 clear-stall 请求保留补丁
- [x] 7.2 验证 Q8B patch 路由、补丁内容一致性及当前 kernel HEAD 适用性

## 8. Q8B 双有线网卡 probe

- [x] 8.1 增加 TC956x IRQ-domain 配置结构体 zero-init 最小 patch
- [x] 8.2 验证 patch 路由、当前 kernel HEAD 适用性及相关配置测试
