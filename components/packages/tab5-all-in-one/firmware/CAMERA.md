# Tab5 相机与 ISP 参考

本页描述当前 SC202CS 摄像头实现。[固件构建与 USB 接口](README.md)负责基础操作。
**当前 ISP 对齐版本只完成宿主测试和两档构建，未完成实机验证。**
旧管线曾实测出图、30 fps CSI、10 fps UVC 及软件 AE（目标 120）；该结果不能证明下面的
硬件统计、目标 62、自动白平衡和标定表在实板上的画质与稳定性。

## 1. 数据路径

```text
SC202CS RAW8 1280×720 @30 fps，CSI 1 lane / 576 Mbps
  → ISP：BF → LSC → Demosaic → CCM → Gamma → Sharp → Color
  → RGB565，经 CSI 桥直通写入 PSRAM（三块 1,843,200 B 缓冲）
  → PPA SRM ×0.5，640×360 RGB565（460,800 B，cache line 对齐）
  → 硬件 JPEG：RGB565 输入、4:2:2、quality 70、双缓冲
  → UVC ISO IN 0x84，448 B/ms（含 2 B 载荷头）
  → Linux uvcvideo，MJPEG 640×360 @10 fps
```

SCCB 地址 `0x36`，共用内部 I2C G31/G32；PID `0xeb52` 从寄存器 `0x3107/0x3108` 读取。
电源使用共享 IO 扩展器 `0x43` 的 PIN6。传感器自带 24 MHz 晶振，没有外接 XCLK 或 RESET 控制脚。
探测不等于配置完成，仍须调用 set_format 写模式表。

640×360 是当前选定模式，PPA 用精确的 8/16 缩放保持 16:9。
PPA 缩放粒度为 1/16，不能把任意目标尺寸当作可精确实现；rev v1.0 的 ISP 无 crop/缩放可代替这一限制。
UVC 只声明一种格式、分辨率和离散帧间隔：1,000,000 个 100 ns，即 100 ms。
典型 JPEG 20–35 KB 需要约 45–78 ms 传输；有效负载预算约 44.6 KB/帧。
不支持多模式协商。

## 2. ESP32-P4 rev v1.0 的硬件边界

| 硬件能力 | 当前处理 |
| --- | --- |
| CSI 桥颜色转换不可用 | CSI input/output 都声明 RGB565，真实 RAW8 去马赛克由上游 ISP 完成 |
| JPEG 不接受 YUV420/YUV444 输入 | 使用 RGB565 输入、4:2:2 编码 |
| ISP WBG、BLC、crop 不可用 | WB 增益折入 CCM；BLC 默认只观测传感器；缩放交给 PPA |
| CCM 为 S2.10 | 实际最大值 3.9990；实现限到 3.990，不能按驱动允许的闭区间直接写 4.0 |
| AWB 主窗统计可用，subwindow 不可用 | 只取主窗四个累加量，不能做官方 5×5 子窗投票 |
| LSC 要求 rev ≥ 1.0 | v1.0 可用，分配 gain array 必须先于 enable |
| 无影子寄存器 | 参数立即生效；换档加迟滞，仍不能承诺帧边界原子更新 |
| DPC / Median 缺少所用 IDF API | 当前未配置 |

CSI 的两个颜色格式同时参与缓冲长度计算。把 input 误写 RAW8 会将 RGB565 帧按一半长度处理，
即使图像入口来自 RAW 传感器也不能这样配置。PPA 输出地址与长度均需 cache line 对齐。

## 3. 当前 ISP 配置

数据来源为 `esp_ipa` 的 `sc202cs_default.json`，通过 `test/isp_cal_extract.py` 提取到
`main/cam_isp_cal.h`。JSON 随 IDF 依赖下载，不随仓库重复维护。
这是复用标定数据与可公开重建的处理逻辑，不宣称与闭源 IPA 调度完全等价。

| 处理级 | 参数与策略 |
| --- | --- |
| BF 双边降噪 | 按传感器增益取 7 档模板/level |
| Demosaic | 按增益取 4 档 gradient_ratio；RGB565 输出已隐式启用，只 configure |
| LSC 暗角 | 21×13 共 273 格 × 4 通道，2410/5210/8200 K 三档最近邻选择 |
| CCM 色彩矩阵 | 官方 19 档按色温线性插值，WB 右乘折入第 0/2 列；向单位阵混合并约束定点范围 |
| Gamma | 4 档，由环境亮度 env.luma 选择；按解析 gamma 生成硬件 16 点折线 |
| Sharp / 对比度 | 按增益取 4 档；色调和亮度设 0 |
| 饱和度 | 按色温选择 2 档 |

前馈级换档迟滞为 3 拍，LSC 为 6 拍；一拍 100 ms。
三档 LSC 是精简后的选择，并非官方九档的完整插值实现；表排列方向及实际暗角效果仍待实板确认。
LSC gain 的定点范围受 2 整数位 + 8 小数位约束，提取脚本检查范围。

`cam_isp_cal.h` 是生成数据。更新依赖后执行：

```bash
# 位于 firmware/，并已激活 ESP-IDF
idf.py build
python3 test/isp_cal_extract.py --check
# 需要更新生成数据时
python3 test/isp_cal_extract.py
```

生成器同时固定 CCT 查表、CCM、LSC 和 gamma 的来源。CCT 使用 16 点单调查表，
提取时修正原拟合曲线的局部非单调段；不能把硬件 gamma 曲线和软件逆表各自独立更新。
软件回算必须逆同一条 16 点折线，不是逆理想解析曲线。

## 4. 曝光、白平衡与直方图

| 统计 | 采样位置 | 调度 | 用途 |
| --- | --- | --- | --- |
| AE 5×5 | demosaic 后、CCM 前 | 连续采集；每 300 ms 调整 | 加权测光与曝光/增益 |
| AWB 主窗白点 | CCM 前 | 每 1 s oneshot | 红/蓝增益与色温，供 CCM/LSC/饱和度 |
| 16 段直方图 | demosaic 后 RGB | 每 1 s，与 AWB 错开 500 ms | env.luma、gamma 与背光场景判定 |

AE 和 AWB 的硬件统计在 CCM/gamma 前，避免将后级变换误当作传感器变化。
AWB 对前级统计求的是绝对建议增益，**不能再乘当前增益**；软件灰世界回退路径采于输出侧，公式不同。
AF 未使用：SC202CS 为定焦，没有对焦马达。

### 主要控制参数

参数集中在 `main/cam_tune.h`，以下为当前默认值和意义；它们的实板表现尚未验收。

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `CAM_AE_TARGET` | 62 | 线性域亮度目标 |
| `CAM_AE_TARGET_LOW/HIGH` | 56 / 64 | 硬件统计路径的非对称死区 |
| `CAM_AE_DAMP_NUM/DEN` | 1 / 2 | 测量/执行存在延迟，使用阻尼 |
| `CAM_AE_STEP_MAX` | 2 | 单步最大倍数 |
| `CAM_AE_GAIN_MAX_MILLI` | 16000 | 传感器增益上限 16× |
| `CAM_AE_INTERVAL_TICKS` | 3 | AE 300 ms 周期 |
| `CAM_AE_HL_OFFSET/LL_OFFSET` | -3 / +1 | 高光/暗部优先的目标平移 |
| `CAM_BACKLIGHT_BRIGHT_PCT` | 25 | 亮块比例达到该值且均值低于目标下限，才选暗部优先 |
| `CAM_CCM_GAIN_R/G/B_MILLI` | 1700 / 1000 / 1550 | WB 初值，红/蓝是估计值，不是最终实测标定 |
| `CAM_CCM_STRENGTH_MAX` | 192 | /256 的色彩强度上限；黑电平尚未测量，不当作最终画质参数 |
| `CAM_CCT_DEFAULT_K` | 5210 | 无可信白点时的色温 |
| `CAM_AWB_MIN_COUNTED` | 1200 | 白点不足不调整增益或色温 |
| `CAM_AWB_RG_MIN/MAX_Q4` | 3801 / 8790 | 白点中心 rg 合法范围，1e-4 定点 |
| `CAM_AWB_BG_MIN/MAX_Q4` | 2903 / 6587 | 白点中心 bg 合法范围 |
| `CAM_AWB_INTERVAL_TICKS` | 10 | AWB 1 s 周期 |
| `CAM_AWB_DEADBAND_PCT` | 5 | 小于 5% 不变 |
| `CAM_AWB_STEP_MAX_PCT` | 25 | 单步限幅，另有 1/2 阻尼 |
| `CAM_AWB_GAIN_MAX_MILLI` | 3445 / 3000 | 硬件白点 / 软件灰世界两条路径的上限 |
| `CAM_STAT_BLC_PEDESTAL` | 0 | 未测得黑电平前，不凭空减基座 |
| `CAM_SENSOR_BLC_ENABLE` | 0 | 仅在 set_format 后读取 0x3902，不写寄存器；不等于传感器物理 BLC 已关闭 |
| `CAM_AWB_ONESHOT_MS`、`CAM_HIST_ONESHOT_MS` | 60 | 不用 0 超时；两者错峰避免阻塞占满 100 ms 帧期 |

软件灰世界回退还有亮度窗口 20..200、单色场景与量化保护；它们不代替硬件白点筛选。
抗工频闪烁、官方 AE 权重加成选择器、官方时域 FIR 和全部 LSC 档位未实现。
黑电平基座、env.luma 的绝对口径及换光源效果需要设备测量。

### 可切换功能

| 开关 | 当前默认 / 作用 |
| --- | --- |
| `CAM_ADN_ENABLE` / `CAM_AEN_ENABLE` | 1，启用 BF/Demosaic 与 Sharp/Color 配置 |
| `CAM_LSC_ENABLE` / `CAM_LSC_BY_CT` | 1，启用 LSC / 按色温选档；固定档默认 5210 K |
| `CAM_CCM_MODE` | 1，官方矩阵；0 为仅白平衡对角阵 |
| `CAM_GAMMA_ENABLE` / `CAM_GAMMA_ADAPTIVE` | 1，gamma / 动态选档；固定档默认 γ=0.5 |
| `CAM_AE_STAT_ENABLE` / `CAM_AE_SOURCE` | 1，建立硬件统计 / 使用硬件测光；source=0 用软件均值 |
| `CAM_AWB_ENABLE` / `CAM_AWB_STAT_ENABLE` / `CAM_AWB_SOURCE` | 1，自动 WB / 硬件统计 / 硬件来源；source=0 为灰世界 |
| `CAM_HIST_ENABLE` / `CAM_ENV_MODEL` | 1，直方图 / 官方 k/ev 模型；model=0 使用断点插值 |
| `CAM_BACKLIGHT_ENABLE` / `CAM_SAT_BY_CT` | 1，场景优先级 / 按色温选饱和度 |
| `CAM_LSC_TRANSPOSE` | 0，标定表方向；只有观测确认方向错误才调整 |

动态 gamma 依赖 gamma + histogram，背光判定依赖 histogram，硬件 AE 来源依赖 AE 统计；
不相容组合在编译期拒绝。关闭 gamma 后软件统计也旁路逆变换，不能只关硬件不改统计口径。

## 5. 接口实现与故障定位

- UVC ISO FIFO 在 SET_CONFIGURATION 分配，不等 alt 1；资源不足可能静默失败。
- `CFG_TUD_VIDEO` 与 `CFG_TUD_VIDEO_STREAMING` 都需声明。
- 当前使用手写 MJPEG 帧描述符规避所锁 TinyUSB 版本的宏问题；描述符的最大帧字节不能写得过小，
  否则主机每包预算缩小，即使端点标着 448 B 也得不到该吞吐。
- `sc202cs_abs_gain_val_map` 的数字增益优先表是 192 档，另一构建分支为 197；控制律限制下标，避开上游边界越界。
- 统计窗口必须明确：AE 按 1280×720 划分，AWB 闭区间右下角为 1279/719。
- 直方图 25 个权重和必须为 256（24×10 + 中心16）；RGB 系数为 86/85/85，15 个阈值严格位于 0..256 内。
- BF、Sharp、Color 配置不能传 NULL；Demosaic 不重复 enable；三个统计块的中断优先级与 ISP 一致。
- LSC 先分配 LUT 再 enable；configure 可在取流中重配。定点换算要处理舍入进位及越界，不能依靠位域截断。
- Color 对比度/饱和度的原生 val 为 1.7 定点，128 表示 1×，不再乘 1000。
- 依赖使用 esp_cam_sensor 与本地控制律，不引入会拉入 USB Host 栈的完整 esp_video。

日志分为 `camera:` 采集/统计/控制和 `uvc:` 编码/传输。先检查 PID、模式、帧长度和 CSI 超时，
再看统计窗口与计数，最后评估控制收敛及颜色；不能在统计全零时调整控制增益。
JPEG 峰值超过约 44 KB 时先降低 quality；30–44 KB 已接近预算，低于 20 KB 且零拒收才有提高质量的空间。

## 6. 设备验证方法

Linux 主机确认实际 video 设备后：

```bash
lsusb -v -d 16d0:10a9
v4l2-ctl --list-devices
v4l2-ctl -d /dev/videoN --list-formats-ext
ffplay -f v4l2 -input_format mjpeg -video_size 640x360 -framerate 10 /dev/videoN
```

缺少节点时先核对主机 uvcvideo 配置和 USB 描述符。实测应分别记录以下结果，当前没有完成表：

| 检查对象 | 观察方法与判据 |
| --- | --- |
| 采集/传输 | CSI 帧长 1,843,200 B，UVC 提交与完成持续增长，无拒收/超时 |
| 统计有效性 | 遮挡、移开和变光时 AE/AWB/HIST 随画面变化；不接受恒零统计 |
| AE / AWB | 稳定光源下停止振荡；切换光源后收敛；纯红/绿/蓝场景不持续推偏 |
| 黑电平 / LSC | 遮光读基座，不预设 16；观察四角、方向与换档闪烁 |
| 复合负载 | 相机开关前后对比同一 GUD 内容，持续双向音频、键盘与触摸，记录真实时间与丢帧 |

纯逻辑验证可在 `firmware/test/` 运行：

```bash
for t in cam_tune cam_frame_stats cam_isp_map; do
    cc -std=c11 -Wall -Wextra -Werror -I../main "test_$t.c" "../main/$t.c" -o "/tmp/tab5-$t"
    "/tmp/tab5-$t"
done
```

现有用例覆盖固定点、增益下标、控制延迟、目标死区、单色场景、CCM 范围、gamma 正反表、
CCT/LSC 选档和 env.luma。软件通过不能替代上述实际设备验证。
