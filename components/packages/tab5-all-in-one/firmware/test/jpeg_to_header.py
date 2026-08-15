#!/usr/bin/env python3
"""把一张 .jpg 机械转成 main/uvc_test_jpeg.h 的 C 数组。

为什么要有这个脚本而不是手贴：静态测试图有两万多字节，手工转换必然出错，
而错了的表现是 host 侧一张花图或者 ffplay 直接报 "Invalid JPEG"，
从现象反推不到"第 8137 个字节抄错了"。做法与 panel_init_data.h /
tab5_kbd_map.h / font8x16.h 一致：**vendor 进来的二进制一律用脚本转，不手抄**。

生成流程（全部可重放，别改中间产物）：
    cd firmware/test
    cc -std=c11 -Wall -Wextra -Werror -I../main test_uvc_pattern.c \\
        ../main/uvc_pattern.c -o /tmp/test_uvc_pattern
    /tmp/test_uvc_pattern /tmp/pattern.ppm
    ffmpeg -y -i /tmp/pattern.ppm -q:v 5 -pix_fmt yuvj422p /tmp/pattern.jpg
    python3 jpeg_to_header.py /tmp/pattern.jpg ../main/uvc_test_jpeg.h

    -q:v 5      ≈ 质量 70，与 cam_jpeg.c 将来的起始 image_quality 同档
    yuvj422p    与固件侧 JPEG_DOWN_SAMPLING_YUV422 一致

⚠️ **静态图也必须走 4:2:2**：P4 Task6 把帧源换成片上硬件编码时，若两边的
   子采样不同，「换了之后图变了」就同时有「编码器」与「子采样」两个变量。
   保持一致，只留一个变量。
   （4:2:0 的 MCU 是 16×16，而 UVC_H = 360 不是 16 的倍数；4:2:2 的 MCU 是
   16×8，640 与 360 都整除 —— 这才是固件侧选 4:2:2 的原因。）
"""
import pathlib
import sys

#
# 上限 44 KB 来自带宽预算（10 fps × 446 B/ms ⇒ 每帧 44.6 KB），超了就发不完。
#
# ⚠️ 下限 **2 KB**，不是 12 KB。计划里写的 12 KB 是按「照片那样的帧」估的，
#    而本图是**纯色块**：8 根平色条 + 一个白方块 + 一条平灰带，几乎没有 AC 系数。
#    实测 -q:v 1/2/5/10 全都落在 2867–2876 字节，12 KB 这个下限**任何质量都够不到**。
#    下限的真实用途只是「别把一张空图/半张图转进来」，2 KB 足够守住这件事。
#    附带的后果要知道：2.9 KB 的帧在 446 B/包下只有 7 个包（最后一个是短包，
#    正好带 EOF），Task5 因此验的是「分包 + EOF 边界」而不是「长帧的持续吞吐」；
#    后者要等 Task6 换成片上编码的真实内容（~20 KB / ~45 包）才谈得上。
MIN_BYTES, MAX_BYTES = 2 * 1024, 44 * 1024


def main():
    if len(sys.argv) != 3:
        raise SystemExit(f'用法：{sys.argv[0]} <输入.jpg> <输出.h>')
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    data = src.read_bytes()

    # JPEG 必须以 SOI(FFD8) 开头、EOI(FFD9) 结尾 —— uvcvideo 会把整个负载原样交给
    # 解码器，少了 EOI 的表现是"画面卡在半张图"，且没有任何错误信息。
    if data[:2] != b'\xff\xd8' or data[-2:] != b'\xff\xd9':
        raise SystemExit(f'{src} 不是完整的 JPEG（缺 SOI 或 EOI）')
    # 上限来自硬约束 B：10 fps × 446 B/ms ⇒ 每帧预算 44.6 KB。超了就是发不完，
    # 表现为实际帧率掉到声明值以下（而描述符仍然说 10 fps）。
    # 下限只是"JPEG 至少得有内容"，防止误把一张空图转进来。
    if not (MIN_BYTES <= len(data) <= MAX_BYTES):
        raise SystemExit(f'{src} 有 {len(data)} 字节，应落在 '
                         f'[{MIN_BYTES}, {MAX_BYTES}]（每帧带宽预算 44.6 KB）')

    rows = [', '.join(f'0x{b:02X}' for b in data[i:i + 12])
            for i in range(0, len(data), 12)]
    dst.write_text(
        '#pragma once\n'
        '/*\n'
        ' * UVC 静态测试图（MJPEG 640×360，4:2:2）。**机械生成，不要手改。**\n'
        ' *\n'
        ' * 来源：main/uvc_pattern.c 渲染 → ffmpeg -q:v 5 -pix_fmt yuvj422p\n'
        ' * 重新生成：见 test/jpeg_to_header.py 的文件头注释。\n'
        ' *\n'
        ' * 用途：P4 Task5 的「先用假数据把 USB 那一层证通」——\n'
        ' * 那一步里没有摄像头、没有 ISP、没有 JPEG 编码器、没有 PPA，\n'
        ' * 只验证 TinyUSB 的 video class 能不能把一段现成的 JPEG 推给 uvcvideo。\n'
        ' *\n'
        ' * 常驻 flash 的 .rodata，**不拷进 RAM**：video_device.c 的\n'
        ' * _prepare_in_payload() 是从这里 memcpy 进 EP 缓冲的，源在 flash 完全没问题。\n'
        ' */\n'
        '#include <stdint.h>\n\n'
        f'/* {len(data)} 字节，每帧带宽预算 44.6 KB（10 fps × 446 B/ms）。 */\n'
        'static const uint8_t k_uvc_test_jpeg[] = {\n'
        + ''.join(f'    {r},\n' for r in rows)
        + '};\n')
    print(f'OK — {len(data)} 字节 → {dst}')


if __name__ == '__main__':
    main()
