# usb-capability-layer Specification

## Purpose

定义 USB 原子能力层的统一接口契约：实例名、内核排序权重、互斥关系、参数模型与生命周期方法，以及各具体能力（adb / ums / ncm / rndis / uvc / uac / mtp / hid / ntb / acm）的行为要求。

## Requirements
### Requirement: 统一能力接口


每个 USB 原子能力 SHALL 实现统一接口，向 L1 gadget 核心层暴露：

| 成员 | 说明 |
|---|---|
| 实例名 | 该能力在 configfs 中的 function 实例名，如 `ffs.adb`、`uvc.gs0`、`mass_storage.0` |
| 排序权重 | 内核对 function 排列顺序的约束，由能力自身声明 |
| 互斥集合 | 与本能力不能共存的其他能力 |
| 参数模型 | 该能力接受的参数及其默认值 |
| prepare | 实例创建后、UDC 绑定前的 configfs 配置 |
| start | UDC 绑定后的启动动作 |
| stop | 停止与清理 |
| status | 当前运行状态 |

L1 SHALL 只通过该接口操作能力，MUST NOT 针对具体能力名称分支。

#### Scenario: 新增能力无需修改核心层

- **WHEN** 新增一个实现了统一接口的能力
- **THEN** 该能力可被场景引用并正常启停，L1 代码无需任何修改

#### Scenario: 能力声明自身排序权重

- **WHEN** L1 需要决定多个能力的实例创建顺序
- **THEN** L1 读取各能力声明的排序权重排序，而非查询硬编码的能力名称顺序表

### Requirement: 能力参数化


能力 SHALL 支持参数，参数由场景定义提供，缺省时使用能力声明的默认值。参数是接口的一等公民，而非可选扩展。

至少以下能力必须支持参数：

- uvc：支持的视频格式与分辨率列表（yuyv / mjpeg / h264）
- ums：backing file 路径、大小、文件系统类型、只读标志、自动挂载策略与挂载点
- hid：protocol、subclass、report 长度与二进制 report descriptor

#### Scenario: 场景提供能力参数

- **WHEN** 场景定义中为 ums 能力指定了 backing file 路径与大小
- **THEN** 该能力启用时使用指定的路径与大小，而非默认值

#### Scenario: 参数缺省时用默认值

- **WHEN** 场景定义引用某能力但未提供其参数
- **THEN** 该能力使用自身声明的默认参数值启用

### Requirement: 能力互斥检查


在启用一组能力前，系统 SHALL 检查其中是否存在互斥组合，存在时 SHALL 拒绝并报告冲突的能力对，且不对 USB 硬件做任何操作。

#### Scenario: 互斥组合被拒绝

- **WHEN** 请求启用的场景同时包含两个互斥的能力
- **THEN** 请求失败并指明冲突的能力对，gadget 保持原状态不变

### Requirement: daemon 生命周期交由 systemd


需要后台 daemon 的能力（如 adb 需要 adbd、mtp 需要 mtp-server）SHALL 通过 systemd unit 管理该 daemon，能力的 start / stop 即为对应 unit 的启动与停止。

系统 MUST NOT 实现自制的守护循环来保活 daemon。

此约束的来源：既有 shell 实现用轮询式自制保活循环，其状态判断读写不对称导致循环泄漏，在 ROCK 5B 上表现为开机 11 分钟堆积 360 余个并发循环、多循环争抢同一 FunctionFS endpoint、USB 每 2 秒断连一次、adb 完全不可用。

#### Scenario: 能力启动即拉起对应 unit

- **WHEN** 启用 adb 能力
- **THEN** 对应的 adbd unit 被启动，adbd 进程在 systemd 的 cgroup 下运行，其输出可通过 journal 查看

#### Scenario: 能力停止即停止对应 unit

- **WHEN** 停用 adb 能力
- **THEN** 对应 unit 被停止，不残留任何保活循环或孤儿进程

#### Scenario: 无自制守护循环

- **WHEN** 检查 L2 实现
- **THEN** 其中不存在轮询重启 daemon 的循环逻辑，daemon 的重启策略完全由 systemd unit 声明

#### Scenario: 反复启停不累积进程

- **WHEN** 连续多次启用与停用同一能力
- **THEN** 系统中该 daemon 的进程数始终不超过 1，无累积

### Requirement: adb 能力


adb 能力 SHALL 在指定路径挂载 FunctionFS，启动 adbd，并在 UDC 绑定前确认 adbd 已实际打开 endpoint 文件描述符。

判定 adbd 就绪 MUST NOT 依赖 endpoint 文件的存在性 —— FunctionFS 挂载后 endpoint inode 即永久存在，与 daemon 是否打开它无关。

#### Scenario: adb 能力启用

- **WHEN** 场景启用 adb 能力
- **THEN** FunctionFS 被挂载，adbd 运行，且 adbd 已打开 endpoint 文件描述符

#### Scenario: 宿主机 adb 连接可用

- **WHEN** 设备通过 USB 连接宿主机，adb 能力已启用
- **THEN** 宿主机 `adb devices` 可发现设备，`adb shell`、`adb push`、`adb pull`、`adb forward`、`adb reverse` 均可正常工作

#### Scenario: 就绪判定不依赖 inode 存在

- **WHEN** FunctionFS 已挂载但 adbd 尚未打开 endpoint
- **THEN** 能力不判定为就绪，继续等待直至 adbd 实际持有文件描述符或超时

### Requirement: ums 能力


ums 能力 SHALL 管理 backing file：文件不存在时按参数指定的大小创建并格式化为指定文件系统；停用时释放 lun 并按自动挂载策略处理本地挂载点。

#### Scenario: 首次启用自动创建 backing file

- **WHEN** 启用 ums 能力而参数指定的 backing file 不存在
- **THEN** 按指定大小创建该文件并格式化为指定文件系统，随后作为 lun 暴露给主机

#### Scenario: 停用后按策略本地挂载

- **WHEN** 停用 ums 能力且参数中自动挂载策略为启用
- **THEN** lun 被释放，backing file 被挂载到指定的本地挂载点

### Requirement: 网络能力


系统 SHALL 提供 USB 网络能力（ncm 与 rndis）。二者互斥。

在既有实现中 rndis 走 configfs 标准 function 的通用路径、无专用配置逻辑，迁移时 SHALL 保持该处理方式，不引入新的配置步骤。

#### Scenario: ncm 与 rndis 互斥

- **WHEN** 场景同时声明 ncm 与 rndis
- **THEN** 请求被拒绝并指明二者冲突

#### Scenario: 网络能力启用后主机可见网卡

- **WHEN** 启用网络能力并连接主机
- **THEN** 主机侧出现对应的 USB 网络接口

### Requirement: uvc 能力


uvc 能力 SHALL 按参数声明的格式与分辨率列表配置 configfs 的 streaming 描述符，支持 yuyv、mjpeg、h264 三类格式，并建立各速度等级所需的 class 链接。

本次变更 SHALL NOT 实现 uvc 的取流 daemon —— 既有实现在该处留有未完成标记，迁移保持此缺口不变。

#### Scenario: 按参数配置多种格式

- **WHEN** 场景为 uvc 能力指定了 mjpeg 与 h264 两类格式及各自的分辨率列表
- **THEN** configfs 中两类格式的描述符均被创建，各分辨率均被配置

#### Scenario: 未声明的格式不配置

- **WHEN** 场景为 uvc 能力只指定了 mjpeg 格式
- **THEN** 只创建 mjpeg 相关描述符，不创建 yuyv 与 h264 描述符

### Requirement: uac 能力


系统 SHALL 提供 uac1 与 uac2 两个音频能力，启用时使能各 feature unit。

#### Scenario: uac 能力启用后主机可见声卡

- **WHEN** 启用 uac 能力并连接主机
- **THEN** 主机侧出现对应的 USB 音频设备

### Requirement: 既有能力不回退


现有 shell 实现中已具备的能力 SHALL 全部迁移，包括 mtp、hid、ntb。迁移以行为等价为准，MUST NOT 借机调整其对外表现。

mtp 能力 SHALL 保留 OS descriptor 的设置与清理；hid 能力 SHALL 保留其 report descriptor 配置；ntb 能力 SHALL 保留其 FunctionFS 挂载。

#### Scenario: mtp 能力行为等价

- **WHEN** 迁移后启用 mtp 能力
- **THEN** OS descriptor 被正确设置，mtp-server 运行，主机侧识别为 MTP 设备；停用时 OS descriptor 被清理

#### Scenario: hid 能力行为等价

- **WHEN** 迁移后启用 hid 能力
- **THEN** report descriptor 与迁移前一致，主机侧识别为对应的 HID 设备

#### Scenario: 迁移未造成能力缺失

- **WHEN** 清点迁移后支持的能力集合
- **THEN** 既有 shell 实现支持的每一个 function 均有对应能力，无遗漏
