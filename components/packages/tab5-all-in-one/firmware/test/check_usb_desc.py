#!/usr/bin/env python3
"""从固件 ELF 里取出 aio_desc_configuration 并逐条校验。

**烧板前的闸门。** 这块板现场没有可用串口（USB-Serial/JTAG 被 TinyUSB 收走、
UART0 只在 M5-Bus 排针上要外接 USB-TTL；唯一的 USB CDC 日志通道 CONFIG_AIO_DEBUG_CDC
本身就要靠改端点账换来，而端点账写错就正是本脚本要拦的东西），
而 UAC1 描述符写错一个字节的表现是「host 完全不认这个设备 / 不出 ALSA 节点」——
没有任何现场证据。手写的 TUD_AUDIO10_* 宏只保证每条 item 的 bLength/tag 自洽，
**不校验** terminal ID 链、wTotalLength、baInterfaceNr 这些跨描述符引用，
那正是本脚本要管的。

用法：
    . $HOME/esp/esp-idf/export.sh
    python3 test/check_usb_desc.py [build/tab5_aio.elf]

依赖 pyelftools（IDF 的 python 环境自带）。
"""
import sys

from elftools.elf.elffile import ELFFile

# 与 main/usb_descriptors.h 的常量一一对应。此处**刻意重复一遍字面量**而不是去
# 解析头文件：本脚本是独立的第二意见，跟着头文件一起改就失去了交叉检查的意义。
#
# ⚠️ 音频是**无条件编译**的（曾经的 CONFIG_AIO_AUDIO_MODE 三档已随排障旋钮删除），
#    所以「没有音频 IAD」本身就是一条失败。唯一还会变的是 CONFIG_AIO_DEBUG_CDC
#    那一档：本脚本按「描述符里有没有 CDC IAD」自动判定，并把判定结果打印出来 ——
#    不去读 sdkconfig，才能保持「独立第二意见」的性质：它只相信 ELF 里真正躺着的
#    那串字节。两档下 GUD/HID/音频那部分的断言完全相同。
EXPECT = dict(
    vid=0x16D0, pid=0x10A9,
    n_itf=7,
    itf_vendor=0, itf_hid=1, itf_ac=2, itf_as_out=3, itf_as_in=4,
    ep_vendor_out=0x01, ep_vendor_in=0x81, ep_hid=0x82,
    ep_audio_out=0x02, ep_audio_in=0x83,
    sample_rate=16000, channels=1, subframe=2, bits=16,
    ep_audio_pkt=36,
    # 播放链上的 Feature Unit（音量 + 静音）。ID 取 5 而非插进 1..4 中间，
    # 见 main/usb_descriptors.h 的 UAC_FU_ID_SPEAKER。
    fu_id=5,
    # bmaControls[0]（master 通道）= MUTE(bit0) | VOLUME(bit1)。
    # 逐通道的 bmaControls[1] 必须是 0：两边都声明会让 snd-usb-audio 建出两个
    # 同名控件（第二个被自动改名成 "...,1"），alsamixer 里出现两根一样的滑块。
    fu_master_bm=0x0003,
    # 排障档 CONFIG_AIO_DEBUG_CDC：让出 GUD 的 IN 端点、借用 UVC 预留的 0x84，
    # 换一条 USB CDC 日志串口。两个接口**追加在音频之后**，vendor/HID/音频的编号全不动。
    itf_cdc=5,
    ep_cdc_in=0x81, ep_cdc_notif=0x84, ep_cdc_out=0x03,
    # ── UVC（P4）────────────────────────────────────────────────
    itf_vc=5, itf_vs=6,
    ep_uvc=0x84, ep_uvc_pkt=448,
    uvc_w=640, uvc_h=360, uvc_interval=1000000,   # 100 ns 单位 ⇒ 10 fps
    uvc_max_frame=65536,
    uvc_cam_term=1, uvc_out_term=2,
    # 调试档下 UVC 顶到 IF2/IF3（音频整体不编译），端点号**不变**
    itf_vc_dbg=2, itf_vs_dbg=3,
)

DESC_CONFIG = 0x02
DESC_STRING = 0x03
DESC_INTERFACE = 0x04
DESC_ENDPOINT = 0x05
DESC_IAD = 0x0B
DESC_HID = 0x21
DESC_CS_INTERFACE = 0x24
DESC_CS_ENDPOINT = 0x25

# UAC1 AudioControl 的 CS 子类型
AC_HEADER, AC_INPUT_TERMINAL, AC_OUTPUT_TERMINAL = 0x01, 0x02, 0x03
AC_FEATURE_UNIT = 0x06
# UAC1 AudioStreaming 的 CS 子类型
AS_GENERAL, AS_FORMAT_TYPE = 0x01, 0x02

# ⚠️ UVC 的 CS 子类型与 UAC1 的**数字重叠**（例如 0x02 在 AC 里是 INPUT_TERMINAL、
#    在 VC 里也是 INPUT_TERMINAL，而 0x01 在 AC 里是 HEADER、在 VS 里是
#    INPUT_HEADER）。所以下面 check_uvc() 收的是**已按所属接口筛过**的两个列表，
#    不是全局 CS_INTERFACE 池 —— 混着找会把音频的 ID1/ID2 端子当成视频的端子，
#    wTotalLength 那条断言会以一个完全指不到病因的数字失败。
# UVC VideoControl 的 CS 子类型
VC_HEADER, VC_INPUT_TERM, VC_OUTPUT_TERM = 0x01, 0x02, 0x03
# UVC VideoStreaming 的 CS 子类型
VS_INPUT_HEADER, VS_FORMAT_MJPEG, VS_FRAME_MJPEG, VS_COLORFORMAT = 0x01, 0x06, 0x07, 0x0D
VIDEO_ITT_CAMERA, VIDEO_TT_STREAMING = 0x0201, 0x0101

# TUSB_ISO_EP_ATT_*：bmAttributes 的 bit3:2
SYNC_NAMES = {0: 'NO_SYNC(!)', 1: 'Asynchronous', 2: 'Adaptive', 3: 'Synchronous'}


def symbol_bytes(path, name):
    """按符号名从 ELF 的**有数据的节**里取出它的字节。"""
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        if symtab is None:
            raise SystemExit('ELF 没有 .symtab（被 strip 过？）')
        syms = symtab.get_symbol_by_name(name)
        if not syms:
            raise SystemExit(f'ELF 里找不到符号 {name}')
        addr, size = syms[0]['st_value'], syms[0]['st_size']
        if size == 0:
            raise SystemExit(f'符号 {name} 的 st_size 为 0，无法取出内容')
        for sec in elf.iter_sections():
            if sec['sh_type'] == 'SHT_NOBITS' or not sec['sh_flags'] & 0x2:
                continue  # 只看 SHF_ALLOC 且有内容的节
            base = sec['sh_addr']
            if base <= addr < base + sec['sh_size']:
                off = addr - base
                return sec.data()[off:off + size]
    raise SystemExit(f'符号 {name} 不在任何有数据的节里')


def walk(buf):
    """把描述符流切成 (bLength, bDescriptorType, 整条 bytes) 的列表。"""
    out, i = [], 0
    while i < len(buf):
        ln = buf[i]
        if ln < 2 or i + ln > len(buf):
            raise SystemExit(f'偏移 {i} 处 bLength={ln} 非法（描述符流不自洽）')
        out.append((ln, buf[i + 1], buf[i:i + ln]))
        i += ln
    return out


def u16(d, o):
    return d[o] | (d[o + 1] << 8)


def u24(d, o):
    return d[o] | (d[o + 1] << 8) | (d[o + 2] << 16)


def check(cond, msg):
    if not cond:
        raise SystemExit(f'FAIL: {msg}')


def check_uvc(iads, eps, vc_csi, vs_csi, itf_by, itf_eps, has_audio):
    """UVC 段的全部跨描述符引用。每条断言都对应一种烧板后才会暴露的错误。

    vc_csi / vs_csi 已由调用方按「所属接口的 class/subclass」筛过（见上方 ⚠️）。
    """
    vc_num = EXPECT['itf_vc'] if has_audio else EXPECT['itf_vc_dbg']
    vs_num = EXPECT['itf_vs'] if has_audio else EXPECT['itf_vs_dbg']

    # 1) IAD：uvcvideo 靠它把 VC+VS 成组绑定；bFunctionClass 必须是 VIDEO(0x0E)
    video_iads = [d for d in iads if d[4] == 0x0E]
    check(len(video_iads) == 1, f'应恰有 1 条 UVC 的 IAD（bFunctionClass=0x0E），实际 {len(video_iads)}')
    iad = video_iads[0]
    check(iad[2] == vc_num and iad[3] == 2,
          f'UVC IAD 应从 IF{vc_num} 起覆盖 2 个接口，实际 first={iad[2]} count={iad[3]}')
    check(iad[5] == 0x03,
          f'bFunctionSubClass 应为 VIDEO_INTERFACE_COLLECTION(3)，实际 {iad[5]}')

    # 2) VideoControl：**必须零端点**（第 5 条 IN 端点会撞 dcd_dwc2 的 TU_ASSERT，且无日志）
    vc = itf_by(vc_num)
    check(vc[4] == 0, f'VideoControl 的 bNumEndpoints={vc[4]}，必须是 0（IN 端点已用满 4/4）')
    check((vc[5], vc[6]) == (0x0E, 0x01), 'VideoControl 的 class/subclass 应为 0x0E/0x01')
    check(itf_eps[(vc_num, 0)] == set(), 'VideoControl 不得带任何端点')

    # 3) VC 头：bcdUVC、wTotalLength、baInterfaceNr
    vch = next((d for d in vc_csi if d[2] == VC_HEADER), None)
    check(vch is not None, '缺 VideoControl 的 CS 头')
    check((vch[3], vch[4]) == (0x50, 0x01),
          f'bcdUVC=0x{vch[4]:02x}{vch[3]:02x}，应为 0x0150（UVC 1.5）')
    n_coll = vch[11]
    check(n_coll == 1, f'bInCollection 应为 1（只有一个 VS 接口），实际 {n_coll}')
    check(vch[12] == vs_num, f'baInterfaceNr 应指向 IF{vs_num}，实际 {vch[12]}')
    # wTotalLength 少算一条，host 就在解析到一半时停下，后面的实体静默消失
    inner = sum(len(d) for d in vc_csi if d[2] in (VC_INPUT_TERM, VC_OUTPUT_TERM))
    check(u16(vch, 5) == len(vch) + inner,
          f'VC 头的 wTotalLength={u16(vch, 5)}，应为 {len(vch) + inner}（头 + 两个端子）')

    # 4) 端子链：Camera(ID1) → Output(ID2)，且 Output 的 bSourceID 指回 ID1
    cam = next((d for d in vc_csi
                if d[2] == VC_INPUT_TERM and d[3] == EXPECT['uvc_cam_term']), None)
    out = next((d for d in vc_csi
                if d[2] == VC_OUTPUT_TERM and d[3] == EXPECT['uvc_out_term']), None)
    check(cam is not None and u16(cam, 4) == VIDEO_ITT_CAMERA,
          'ID1 应为 Camera Terminal(wTerminalType=0x0201)')
    check(out is not None and u16(out, 4) == VIDEO_TT_STREAMING,
          'ID2 应为 USB Streaming 输出端子(wTerminalType=0x0101)')
    check(out[7] == EXPECT['uvc_cam_term'],
          f'输出端子的 bSourceID={out[7]}，应为 {EXPECT["uvc_cam_term"]}（视频链断了）')

    # 5) VideoStreaming：alt 0 零端点（带宽零和的落点）、alt 1 恰一条 ISO IN
    check(itf_eps[(vs_num, 0)] == set(),
          'VideoStreaming alt 0 必须零端点 —— host 不开摄像头时不预留 ISO 带宽')
    check(itf_eps[(vs_num, 1)] == {EXPECT['ep_uvc']},
          f'VideoStreaming alt 1 应恰有一条端点 0x{EXPECT["ep_uvc"]:02X}')
    ep = next(d for d in eps if d[2] == EXPECT['ep_uvc'])
    check(ep[0] == 7,
          f'UVC 的 ISO 端点描述符应为 7 字节（标准端点），实际 {ep[0]} —— '
          '9 字节是 UAC1 的形式，说明有人手写错了')
    check(ep[3] & 0x03 == 0x01, 'UVC 端点必须是 isochronous')
    check((ep[3] >> 2) & 0x03 == 0x01,
          'UVC 端点的 sync 类型应为 asynchronous（TUD_VIDEO_DESC_EP_ISO 写死的值）')
    check(u16(ep, 4) == EXPECT['ep_uvc_pkt'],
          f'UVC 端点 wMaxPacketSize={u16(ep, 4)}，应为 {EXPECT["ep_uvc_pkt"]}；'
          'DWC2 的 dfifo 只剩 123 words=492 字节，超了会静默 STALL')
    check(ep[6] == 1, 'bInterval 应为 1（每个 USB 帧一包）')

    # 6) VS 输入头：bEndpointAddress、bTerminalLink、wTotalLength
    vsh = next((d for d in vs_csi if d[2] == VS_INPUT_HEADER), None)
    check(vsh is not None, '缺 VideoStreaming 的输入头')
    check(vsh[3] == 1, f'bNumFormats 应为 1，实际 {vsh[3]}')
    check(vsh[6] == EXPECT['ep_uvc'],
          f'VS 头里的 bEndpointAddress=0x{vsh[6]:02X}，应为 0x{EXPECT["ep_uvc"]:02X}')
    check(vsh[8] == EXPECT['uvc_out_term'],
          f'bTerminalLink={vsh[8]}，应指向输出端子 ID{EXPECT["uvc_out_term"]}')
    check(vsh[9] == 0, 'bStillCaptureMethod 应为 0（不做静态抓拍）')
    fmt = next(d for d in vs_csi if d[2] == VS_FORMAT_MJPEG)
    frm = next(d for d in vs_csi if d[2] == VS_FRAME_MJPEG)
    color = next(d for d in vs_csi if d[2] == VS_COLORFORMAT)
    check(u16(vsh, 4) == len(vsh) + len(fmt) + len(frm) + len(color),
          'VS 头的 wTotalLength 与「头 + 格式 + 帧 + 色彩匹配」不符')

    # 7) 格式与帧：MJPEG、640×360、单一离散帧间隔、dwMaxVideoFrameBufferSize
    check(fmt[3] == 1 and fmt[4] == 1, 'bFormatIndex/bNumFrameDescriptors 都应为 1')
    check(frm[3] == 1, 'bFrameIndex 应为 1')
    check(u16(frm, 5) == EXPECT['uvc_w'] and u16(frm, 7) == EXPECT['uvc_h'],
          f'帧尺寸应为 {EXPECT["uvc_w"]}×{EXPECT["uvc_h"]}，'
          f'实际 {u16(frm, 5)}×{u16(frm, 7)}')
    max_frame = int.from_bytes(frm[17:21], 'little')
    interval = int.from_bytes(frm[21:25], 'little')
    n_intv = frm[25]
    # ★ 手写的 AIO_UVC_FRM_MJPEG_DISC1 就是为这条断言存在的：TinyUSB 库里那个
    #   TUD_VIDEO_DESC_CS_VS_FRM_MJPEG_DISC 宏会让 bLength 与实际字节数不符
    #   （见 usb_descriptors.c 的 ⚠️），错位后这里读到的全是垃圾。
    check(len(frm) == 26 + 4,
          f'离散帧描述符应为 30 字节（26 + 1 个 4 字节间隔），实际 {len(frm)}')
    check(n_intv == 1,
          f'bFrameIntervalType 应为 1（单一离散间隔），实际 {n_intv} —— '
          '连续区间会让 video_device.c 的默认值协商走进"什么都不填"的分支')
    check(interval == EXPECT['uvc_interval'],
          f'dwDefaultFrameInterval={interval}，应为 {EXPECT["uvc_interval"]}'
          f'（{EXPECT["uvc_interval"] // 10000} ms ⇒ {10000000 // EXPECT["uvc_interval"]} fps）')
    check(int.from_bytes(frm[26:30], 'little') == interval,
          '唯一的那个离散帧间隔与 dwDefaultFrameInterval 不一致')
    check(max_frame == EXPECT['uvc_max_frame'],
          f'dwMaxVideoFrameBufferSize={max_frame}，应为 {EXPECT["uvc_max_frame"]}')
    # ★ 那条静默的带宽陷阱：max_frame/interval_ms + 2 必须 > 端点包大小，
    #   否则 TinyUSB 会把每包缩小，带宽白掉一截而哪里都不报错
    interval_ms = interval // 10000
    check(max_frame // interval_ms + 2 > EXPECT['ep_uvc_pkt'],
          f'dwMaxVideoFrameBufferSize 太小：{max_frame}/{interval_ms}+2='
          f'{max_frame // interval_ms + 2} ≤ {EXPECT["ep_uvc_pkt"]}，'
          'TinyUSB 会把 dwMaxPayloadTransferSize 缩到这个值（video_device.c:562-567）')
    check(color[3] == 0x01, 'bColorPrimaries 应为 BT.709')


def main():
    elf = sys.argv[1] if len(sys.argv) > 1 else 'build/tab5_aio.elf'

    # ── 设备描述符：VID/PID 是 drm/gud 绑定的固定 modalias，不可漂 ──
    dev = symbol_bytes(elf, 'aio_desc_device')
    check(dev[0] == 18 and dev[1] == 0x01, '设备描述符不是 18 字节的 DEVICE')
    check(u16(dev, 8) == EXPECT['vid'] and u16(dev, 10) == EXPECT['pid'],
          f'VID/PID 是 {u16(dev, 8):04x}:{u16(dev, 10):04x}，'
          f'应为 {EXPECT["vid"]:04x}:{EXPECT["pid"]:04x}（gud 绑定所需）')
    check((dev[4], dev[5], dev[6]) == (0xEF, 0x02, 0x01),
          '设备描述符必须是 Misc/IAD(239/2/1)，否则 host 不会按 IAD 成组绑定音频')

    cfg = symbol_bytes(elf, 'aio_desc_configuration')
    items = walk(cfg)

    # ── 1) 配置描述符自洽 ──
    check(items[0][1] == DESC_CONFIG, '第一条必须是 CONFIGURATION')
    total = u16(items[0][2], 2)
    check(total == len(cfg), f'wTotalLength={total} 与实际长度 {len(cfg)} 不符')
    n_itf_declared = items[0][2][4]

    # ── 2) 分类收集 ──
    # ⚠️ CS_INTERFACE 的 bDescriptorSubtype 在 AudioControl 与 AudioStreaming 两个
    #    子类里**是两套独立的编号**（例如 0x02 在 AC 里是 INPUT_TERMINAL，在 AS 里
    #    是 FORMAT_TYPE）。所以必须按出现顺序记住「当前属于哪个接口」，
    #    不能把全部 CS_INTERFACE 混成一个池子去按 subtype 过滤。
    itfs, eps, iads = [], [], []
    ac_csi, as_csi, cse = [], [], []   # as_csi 元素为 (接口号, 描述符)
    vc_csi, vs_csi = [], []            # UVC 的两套，同样必须按所属接口分开
    itf_eps = {}                       # (接口号, alt) -> 该 alt 下声明的端点地址集合
    cur = None
    for ln, typ, d in items:
        if typ == DESC_INTERFACE:
            itfs.append(d)
            cur = d
            itf_eps.setdefault((d[2], d[3]), set())
        elif typ == DESC_ENDPOINT:
            eps.append(d)
            check(cur is not None, 'ENDPOINT 出现在任何 INTERFACE 之前')
            itf_eps[(cur[2], cur[3])].add(d[2])
        elif typ == DESC_CS_INTERFACE:
            check(cur is not None, 'CS_INTERFACE 出现在任何 INTERFACE 之前')
            if (cur[5], cur[6]) == (0x01, 0x01):        # AUDIO / AUDIOCONTROL
                ac_csi.append(d)
            elif (cur[5], cur[6]) == (0x01, 0x02):      # AUDIO / AUDIOSTREAMING
                as_csi.append((cur[2], d))
            elif (cur[5], cur[6]) == (0x0E, 0x01):      # VIDEO / VIDEOCONTROL
                vc_csi.append(d)
            elif (cur[5], cur[6]) == (0x0E, 0x02):      # VIDEO / VIDEOSTREAMING
                vs_csi.append(d)
        elif typ == DESC_CS_ENDPOINT:
            cse.append(d)
        elif typ == DESC_IAD:
            iads.append(d)
    csi = ac_csi

    # 编了哪些可选功能，一律由 IAD 的 bFunctionClass 判定 —— 不读 sdkconfig，
    # 才保得住「独立第二意见」的性质：只相信 ELF 里真正躺着的那串字节。
    audio_iads = [d for d in iads if d[4] == 0x01]   # AUDIO
    cdc_iads = [d for d in iads if d[4] == 0x02]     # CDC Control
    has_cdc = len(cdc_iads) > 0
    has_audio = len(audio_iads) > 0
    n_itf = EXPECT['n_itf'] + (2 if has_cdc else 0)
    mode = '默认档：GUD + HID + UAC1 音频 + UVC 摄像头'
    if has_cdc:
        mode += ' + CDC 排障档 (CONFIG_AIO_DEBUG_CDC=y，已让出 GUD 的 IN 端点)'
    print(f'== 模式：{mode} ==\n')

    itf_nums = sorted({d[2] for d in itfs})
    check(itf_nums == list(range(n_itf)),
          f'接口号应为 0..{n_itf - 1}，实际 {itf_nums}')
    check(n_itf_declared == n_itf,
          f'bNumInterfaces={n_itf_declared}，实际有 {n_itf} 个接口')

    def itf_by(num, alt=0):
        for d in itfs:
            if d[2] == num and d[3] == alt:
                return d
        raise SystemExit(f'FAIL: 找不到 IF{num} alt{alt}')

    # ── 3) 已验证功能的接口/端点**没有被音频改动** ──
    #    这是「不破坏 GUD / HID」那条硬约束在宿主机上唯一能查的部分。
    vendor = itf_by(EXPECT['itf_vendor'])
    check(vendor[5] == 0xFF, 'IF0 必须是 vendor 类(0xFF)，drm/gud 按它绑定')
    hid = itf_by(EXPECT['itf_hid'])
    check(hid[5] == 0x03, 'IF1 必须是 HID 类(0x03)')
    ep_addrs = {d[2] for d in eps}
    for name in ('ep_vendor_out', 'ep_hid'):
        check(EXPECT[name] in ep_addrs, f'{name}=0x{EXPECT[name]:02X} 不见了')

    # vendor(GUD) 的 IN 端点：正常档必须在；CDC 排障档必须**不在**（那条 IN 让给了 CDC）。
    # drm/gud 的 gud_probe() 只找 bulk OUT，从不找 bulk IN，所以让掉它不影响显示；
    # 但「以为让掉了其实还在」会让 IN 端点超编、dcd_dwc2 静默失败，所以两边都钉死。
    #
    # ⚠️ 必须按**接口**查而不是按全局地址查：CDC 档里 0x81 被 CDC 数据 IN 接手了，
    #    「0x81 还在描述符里」并不代表 vendor 还占着它。
    vendor_eps = itf_eps[(EXPECT['itf_vendor'], 0)]
    if has_cdc:
        check(vendor_eps == {EXPECT['ep_vendor_out']},
              f'CDC 排障档下 IF0(vendor) 只该剩 bulk OUT，实际 '
              f'{{{", ".join(f"0x{a:02X}" for a in sorted(vendor_eps))}}} —— '
              'IN 端点没让出去会超编，而 dcd_dwc2 超编时一个字都不打')
    else:
        check(vendor_eps == {EXPECT['ep_vendor_out'], EXPECT['ep_vendor_in']},
              f'IF0(vendor) 应为 bulk OUT + bulk IN，实际 '
              f'{{{", ".join(f"0x{a:02X}" for a in sorted(vendor_eps))}}}')
    check(vendor[4] == len(vendor_eps),
          f'IF0(vendor) 的 bNumEndpoints={vendor[4]}，与实际声明的 {len(vendor_eps)} 条不符')

    # ── 端点总账：所有模式都要守 ──
    # UVC 落地后 4 条可用 IN 端点**全部用满**，所以这里从「≤ 4」升级成「恰好是这四条」：
    # 少一条说明某个功能的端点没编进去，多一条会撞 dcd_dwc2.c 的
    # TU_ASSERT(allocated_epin_count < ep_in_count)，而它一个字都不打。
    in_eps = sorted({d[2] for d in eps if d[2] & 0x80})
    check(in_eps == [0x81, 0x82, 0x83, 0x84],
          f'IN 端点应恰为 [0x81,0x82,0x83,0x84]（4/4 用满），实际 {[hex(a) for a in in_eps]}')
    iso_in = {d[2] for d in eps if d[2] & 0x80 and d[3] & 0x03 == 0x01}
    check(EXPECT['ep_uvc'] in iso_in,
          '0x84 必须是 UVC 的 ISO IN —— 它是最后一条可用 IN 端点')

    # ── CDC 排障档：接口/端点账 ──
    if has_cdc:
        itf_cdc = EXPECT['itf_cdc']
        itf_cdc_data = itf_cdc + 1
        check(len(cdc_iads) == 1, f'应恰有 1 条 CDC IAD，实际 {len(cdc_iads)}')
        cdc_iad = cdc_iads[0]
        check(cdc_iad[2] == itf_cdc and cdc_iad[3] == 2,
              f'CDC 的 IAD 应从 IF{itf_cdc} 起覆盖 2 个接口，'
              f'实际 first={cdc_iad[2]} count={cdc_iad[3]}')
        cdc_ctl = itf_by(itf_cdc)
        cdc_dat = itf_by(itf_cdc_data)
        check((cdc_ctl[5], cdc_ctl[6]) == (0x02, 0x02),
              'CDC 控制接口必须是 CDC/ACM(2/2)')
        check(cdc_dat[5] == 0x0A, 'CDC 数据接口必须是 CDC-Data 类(0x0A)')
        check(itf_eps[(itf_cdc, 0)] == {EXPECT['ep_cdc_notif']},
              f'CDC 控制接口应只有通知端点 0x{EXPECT["ep_cdc_notif"]:02X}')
        check(itf_eps[(itf_cdc_data, 0)] == {EXPECT['ep_cdc_out'], EXPECT['ep_cdc_in']},
              f'CDC 数据接口应为 0x{EXPECT["ep_cdc_out"]:02X} + 0x{EXPECT["ep_cdc_in"]:02X}')
        # 端点地址全局唯一 —— 与音频/HID 撞号是这一档最容易踩的坑，
        # 而撞号的表现是「某个接口静默不工作」，从现象几乎反推不出来。
        check(len({d[2] for d in eps}) == len(eps), '有端点地址重复声明')

    # ── 4) IAD 覆盖三个音频接口（音频无条件编译，缺了就是失败）──
    check(len(audio_iads) == 1, f'应恰有 1 条音频 IAD，实际 {len(audio_iads)}')
    iad = audio_iads[0]
    check(iad[2] == EXPECT['itf_ac'] and iad[3] == 3,
          f'IAD 应从 IF{EXPECT["itf_ac"]} 起覆盖 3 个接口，实际 first={iad[2]} count={iad[3]}')
    check(iad[4] == 0x01, 'IAD 的 bFunctionClass 必须是 AUDIO(0x01)')

    # ── 5) AudioControl：接口类、AC 头、终端链 ──
    ac = itf_by(EXPECT['itf_ac'])
    check((ac[5], ac[6]) == (0x01, 0x01), 'AC 接口必须是 AUDIO/AUDIOCONTROL(1/1)')
    check(ac[4] == 0, 'AC 接口不应带端点（我们关掉了中断端点，省一条 IN）')

    ac_hdr = next((d for d in csi if d[2] == AC_HEADER and d[0] >= 8), None)
    check(ac_hdr is not None, '缺 AudioControl 的 CS 头描述符')
    check(u16(ac_hdr, 3) == 0x0100, 'bcdADC 必须是 0x0100(UAC 1.0)')
    n_coll = ac_hdr[7]
    check(n_coll == 2, f'bInCollection 应为 2（播放 + 录音），实际 {n_coll}')
    ba = list(ac_hdr[8:8 + n_coll])
    check(ba == [EXPECT['itf_as_out'], EXPECT['itf_as_in']],
          f'baInterfaceNr 应为 {[EXPECT["itf_as_out"], EXPECT["itf_as_in"]]}，实际 {ba}')
    # AC 头的 wTotalLength 必须覆盖它自己 + 全部终端/单元描述符。
    # ⚠️ 新增实体（如 Feature Unit）时这个集合要跟着扩：少算一条的表现是 host 解析
    #    到一半就停，后面的实体静默消失（「声卡在但没有音量」）。
    units = [d for d in csi
             if d[2] in (AC_INPUT_TERMINAL, AC_OUTPUT_TERMINAL, AC_FEATURE_UNIT)]
    ac_total = u16(ac_hdr, 5)
    check(ac_total == ac_hdr[0] + sum(d[0] for d in units),
          f'AC 头的 wTotalLength={ac_total}，与「AC 头 + 全部终端/单元」的实际长度不符')

    # 终端 ID 链：ID1(USB流) → ID5(Feature Unit) → ID2(喇叭)，ID3(麦克风) → ID4(USB流)
    in_terms = {d[3]: d for d in csi if d[2] == AC_INPUT_TERMINAL}
    out_terms = {d[3]: d for d in csi if d[2] == AC_OUTPUT_TERMINAL}
    check(sorted(in_terms) == [1, 3] and sorted(out_terms) == [2, 4],
          f'终端 ID 应为输入 {{1,3}} / 输出 {{2,4}}，实际 输入{sorted(in_terms)} 输出{sorted(out_terms)}')
    check(u16(in_terms[1], 4) == 0x0101, 'ID1 应是 USB Streaming(0x0101) 输入端子')
    check(u16(out_terms[2], 4) == 0x0301, 'ID2 应是 Generic Speaker(0x0301) 输出端子')

    # ── 5b) 播放侧 Feature Unit：音量/静音落到 ES8388 硬件的入口 ──
    # 描述符错一位的表现是「alsamixer 里没有这个通道」或「有滑块但拖了不出声」，
    # 而 host 侧不会报任何错 —— 这正是本脚本存在的理由。
    fus = [d for d in csi if d[2] == AC_FEATURE_UNIT]
    check(len(fus) == 1,
          f'播放链上应恰有 1 个 Feature Unit（录音侧刻意不放），实际 {len(fus)}')
    fu = fus[0]
    check(fu[3] == EXPECT['fu_id'],
          f'Feature Unit 的 bUnitID={fu[3]}，应为 {EXPECT["fu_id"]}'
          '（codec_audio.c 的控制请求回调按这个数寻址）')
    check(fu[4] == 1, f'Feature Unit 的 bSourceID={fu[4]}，必须指向 ID1(USB 流输入端子)')
    check(fu[5] == 2, f'Feature Unit 的 bControlSize={fu[5]}，应为 2（每通道 16 位位图）')
    # 布局：[6:8]bmaControls[0] master，[8:10]bmaControls[1] 通道1，[10]iFeature
    check(fu[0] == 7 + 2 * (EXPECT['channels'] + 1),
          f'Feature Unit 的 bLength={fu[0]}，与「master + {EXPECT["channels"]} 个通道」'
          '的位图个数对不上')
    check(u16(fu, 6) == EXPECT['fu_master_bm'],
          f'Feature Unit 的 master 位图=0x{u16(fu, 6):04x}，'
          f'应为 0x{EXPECT["fu_master_bm"]:04x}（Mute + Volume）')
    check(u16(fu, 8) == 0,
          f'Feature Unit 的通道 1 位图=0x{u16(fu, 8):04x}，必须为 0 —— '
          '与 master 重复声明会让 snd-usb-audio 建出两根同名滑块')
    check(out_terms[2][7] == EXPECT['fu_id'],
          f'ID2 的 bSourceID={out_terms[2][7]}，应指向 Feature Unit '
          f'ID{EXPECT["fu_id"]}（音量被绕过了，或播放链断了）')

    check(u16(in_terms[3], 4) == 0x0201, 'ID3 应是 Generic Microphone(0x0201) 输入端子')
    check(u16(out_terms[4], 4) == 0x0101, 'ID4 应是 USB Streaming(0x0101) 输出端子')
    check(out_terms[4][7] == 3, 'ID4 的 bSourceID 必须指向 ID3（录音链断了）')
    for tid in (1, 3):
        # 输入端子布局：..[3]bTerminalID [4:6]wTerminalType [6]bAssocTerminal [7]bNrChannels
        check(in_terms[tid][7] == EXPECT['channels'],
              f'ID{tid} 的 bNrChannels 应为 {EXPECT["channels"]}')

    # ── 6) 两条 AudioStreaming：alt 0 零带宽 + alt 1 带端点 ──
    for num, link, sync_want, epaddr in (
        (EXPECT['itf_as_out'], 1, 2, EXPECT['ep_audio_out']),   # 播放：adaptive
        (EXPECT['itf_as_in'],  4, 1, EXPECT['ep_audio_in']),    # 录音：asynchronous
    ):
        alts = [d for d in itfs if d[2] == num]
        check(sorted(d[3] for d in alts) == [0, 1],
              f'IF{num} 必须有 alt0/alt1 两个设置，实际 {sorted(d[3] for d in alts)}')
        a0 = itf_by(num, 0)
        a1 = itf_by(num, 1)
        check((a0[5], a0[6]) == (0x01, 0x02) and (a1[5], a1[6]) == (0x01, 0x02),
              f'IF{num} 必须是 AUDIO/AUDIOSTREAMING(1/2)')
        check(a0[4] == 0, f'IF{num} alt0 必须是零带宽（0 个端点），否则 host 一直占 ISO 预留')
        check(a1[4] == 1, f'IF{num} alt1 必须恰有 1 个端点')

        # 该接口的 AS_GENERAL 的 bTerminalLink 必须接到对应的终端
        gen = [d for i, d in as_csi if i == num and d[2] == AS_GENERAL and d[0] == 7]
        check(len(gen) == 1, f'IF{num} 应恰有 1 条 AS_GENERAL，实际 {len(gen)}')
        check(gen[0][3] == link,
              f'IF{num} 的 bTerminalLink={gen[0][3]}，应指向终端 ID{link}')

        # 端点
        ep = next((d for d in eps if d[2] == epaddr), None)
        check(ep is not None, f'找不到端点 0x{epaddr:02X}')
        check(ep[0] == 9,
              f'端点 0x{epaddr:02X} 的描述符必须是 9 字节'
              '（UAC1 的 ISO 数据端点含 bRefresh/bSynchAddress）')
        check(ep[3] & 0x03 == 0x01, f'端点 0x{epaddr:02X} 必须是 isochronous')
        check(u16(ep, 4) == EXPECT['ep_audio_pkt'],
              f'端点 0x{epaddr:02X} 的 wMaxPacketSize={u16(ep, 4)}，'
              f'应为 {EXPECT["ep_audio_pkt"]}')
        check(ep[6] == 1, f'端点 0x{epaddr:02X} 的 bInterval 应为 1（每帧一包）')
        sync = (ep[3] >> 2) & 0x03
        check(sync == sync_want,
              f'端点 0x{epaddr:02X} 的 sync 字段是 {SYNC_NAMES[sync]}，应为 {SYNC_NAMES[sync_want]}')

    # ── 7) ★硬约束：没有反馈端点，且 ISO 端点的 sync 字段都不为 0 ──
    # UVC 落地后共 3 条 ISO：UAC 播放 OUT + UAC 录音 IN + UVC 视频 IN。
    iso_eps = [d for d in eps if d[3] & 0x03 == 0x01]
    check(len(iso_eps) == 3,
          f'应恰有 3 条 ISO 端点（UAC 两条 + UVC 一条），实际 {len(iso_eps)}')
    for d in iso_eps:
        sync = (d[3] >> 2) & 0x03
        check(sync != 0,
              f'端点 0x{d[2]:02X} 的 sync 字段为 0(NO_SYNC) —— '
              'TinyUSB 的 UAC1 分支会把它当成反馈端点，数据永远发不出去')
        # bSynchAddress 只存在于 UAC1 那种 9 字节的 ISO 数据端点描述符上；
        # UVC 用的是标准 7 字节端点，压根没有这个字段（也因此没有反馈端点这回事）。
        if d[0] == 9:
            check(d[8] == 0,
                  f'端点 0x{d[2]:02X} 的 bSynchAddress=0x{d[8]:02X} 非 0 —— '
                  '引入了显式反馈端点，会占掉 0x84 把 UVC 顶出去')

    # ── 8) Type I 格式与预期参数一致（两条 AS 各一份，必须都对） ──
    fmts = [d for _, d in as_csi if d[2] == AS_FORMAT_TYPE]
    check(len(fmts) == 2, f'应有 2 份 Type I Format 描述符，实际 {len(fmts)}')
    for d in fmts:
        check(d[3] == 0x01, 'bFormatType 必须是 FORMAT_TYPE_I')
        check(d[4] == EXPECT['channels'], f'bNrChannels={d[4]}，应为 {EXPECT["channels"]}')
        check(d[5] == EXPECT['subframe'], f'bSubframeSize={d[5]}，应为 {EXPECT["subframe"]}')
        check(d[6] == EXPECT['bits'], f'bBitResolution={d[6]}，应为 {EXPECT["bits"]}')
        check(d[7] == 1, f'bSamFreqType={d[7]}，本阶段只声明一个离散采样率')
        rate = u24(d, 8)
        check(rate == EXPECT['sample_rate'],
              f'采样率 {rate} 与预期 {EXPECT["sample_rate"]} 不符')
        check(rate % 1000 == 0,
              f'采样率 {rate} 不是 1000 的整数倍 —— 会产生小数包，必须上反馈端点')

    # 每条数据端点后面都得跟一条 CS 端点（AS_ISO_EP General）。
    # UVC 的 ISO 端点**没有** CS 端点描述符，所以这个数不受视频影响。
    check(len(cse) == 2, f'应有 2 条 CS 端点描述符，实际 {len(cse)}')

    # ── 9) UVC：IAD / 端子链 / alt0 零带宽 / 0x84 的包大小与帧参数 ──
    check_uvc(iads, eps, vc_csi, vs_csi, itf_by, itf_eps, has_audio)

    # ── 打印描述符树 ──
    kind = {DESC_CONFIG: 'CONFIG', DESC_STRING: 'STRING', DESC_INTERFACE: 'INTERFACE',
            DESC_ENDPOINT: 'ENDPOINT', DESC_IAD: 'IAD', DESC_HID: 'HID',
            DESC_CS_INTERFACE: 'CS_INTERFACE', DESC_CS_ENDPOINT: 'CS_ENDPOINT'}
    for ln, typ, d in items:
        note = ''
        if typ == DESC_INTERFACE:
            note = f'  <- IF{d[2]} alt{d[3]} class={d[5]:02x}/{d[6]:02x} nEP={d[4]}'
        elif typ == DESC_ENDPOINT:
            note = f'  <- EP 0x{d[2]:02X} attr=0x{d[3]:02X} mps={u16(d, 4)}'
            if d[3] & 3 == 1:
                note += f' sync={SYNC_NAMES[(d[3] >> 2) & 3]}'
                # bSynchAddress 只在 UAC1 那种 9 字节形式里有；UVC 是标准 7 字节。
                if ln == 9:
                    note += f' bSynchAddress={d[8]}'
        print(f'  {kind.get(typ, hex(typ)):<13} len={ln:<3} {d.hex()}{note}')

    print(f'\nOK — GUD + HID + UAC1 音频 + UVC 摄像头：'
          f'{len(cfg)} 字节 / {n_itf} 接口 / '
          f'{len(iso_eps)} 条 ISO 端点 / {len(in_eps)} 条 IN 端点 '
          f'({", ".join(f"0x{a:02X}" for a in in_eps)}) / 无反馈端点 / '
          f'播放链 ID1→ID{EXPECT["fu_id"]}(FU:Mute+Volume)→ID2')
    print(f'  UVC: MJPEG {EXPECT["uvc_w"]}×{EXPECT["uvc_h"]} @ '
          f'{10000000 // EXPECT["uvc_interval"]} fps, ISO IN 0x{EXPECT["ep_uvc"]:02X} '
          f'× {EXPECT["ep_uvc_pkt"]} B/帧 = {EXPECT["ep_uvc_pkt"] - 2} B/ms 有效载荷；'
          f'视频链 ID{EXPECT["uvc_cam_term"]}(Camera)→ID{EXPECT["uvc_out_term"]}(USB Streaming)')


# 既能当脚本跑，也能被 import 复用 symbol_bytes()：Task 3 的「vendor/HID/UAC 三段
# 逐字节未变」对比就是靠 import 这个模块做的，模块级直接 main() 会在 import 时炸。
if __name__ == '__main__':
    main()
