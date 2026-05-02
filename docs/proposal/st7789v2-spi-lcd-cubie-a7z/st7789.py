#!/usr/bin/env python3
"""ST7789V2 240x280 SPI LCD bring-up on Cubie A7Z (Allwinner A733).

Wiring (40-pin header):
  SPI1 MOSI -> PD11 (header pin 19)
  SPI1 SCLK -> PD12 (header pin 23)
  CS  (GPIO software) -> PB3, gpiochip0 line 35, header pin 31
  DC  (GPIO)          -> PB5, gpiochip0 line 37, header pin 12
  RES (GPIO)          -> PB6, gpiochip0 line 38, header pin 35
  BLK (GPIO)          -> PB4, gpiochip0 line 36, header pin 36

We use /dev/spidev1.0 in mode 0 with software CS via libgpiod, because PB3's
SPI mux is SPI2_CS0 — not usable as SPI1 hardware CS. The spidev1 overlay
exposes one chipselect on PD10 we ignore (no_cs is not portable; instead we
hold the kernel CS high implicitly by never connecting it).
"""

from __future__ import annotations

import argparse
import time

import gpiod
import spidev

CHIP = "gpiochip0"
LINE_CS = 35
LINE_BLK = 36
LINE_DC = 37
LINE_RES = 38

WIDTH = 240
HEIGHT = 280


class ST7789:
    def __init__(self, spi_bus=1, spi_dev=0, hz=40_000_000,
                 x_offset=0, y_offset=20):
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_dev)
        self.spi.mode = 0
        self.spi.max_speed_hz = hz
        self.spi.bits_per_word = 8

        self.chip = gpiod.Chip(CHIP)
        self.cs = self._req(LINE_CS, default=1)
        self.dc = self._req(LINE_DC, default=0)
        self.res = self._req(LINE_RES, default=1)
        self.blk = self._req(LINE_BLK, default=0)

        self.x_offset = x_offset
        self.y_offset = y_offset

    def _req(self, line, default):
        ln = self.chip.get_line(line)
        ln.request(consumer="st7789", type=gpiod.LINE_REQ_DIR_OUT,
                   default_vals=[default])
        return ln

    # --- low-level ---

    def _cmd(self, cmd, *data):
        self.dc.set_value(0)
        self.cs.set_value(0)
        self.spi.writebytes([cmd])
        self.cs.set_value(1)
        if data:
            self._data(*data)

    def _data(self, *data):
        self.dc.set_value(1)
        self.cs.set_value(0)
        # writebytes2 handles big buffers via chunks
        self.spi.writebytes2(list(data) if isinstance(data[0], int) else data[0])
        self.cs.set_value(1)

    def _data_bytes(self, buf):
        self.dc.set_value(1)
        self.cs.set_value(0)
        self.spi.writebytes2(buf)
        self.cs.set_value(1)

    # --- init ---

    def reset(self):
        self.res.set_value(1); time.sleep(0.01)
        self.res.set_value(0); time.sleep(0.01)
        self.res.set_value(1); time.sleep(0.12)

    def init(self):
        self.reset()
        self._cmd(0x11)                                   # SLPOUT
        time.sleep(0.12)
        self._cmd(0x36, 0x00)                             # MADCTL
        self._cmd(0x3A, 0x55)                             # COLMOD: 16-bit RGB565
        self._cmd(0xB2, 0x0C, 0x0C, 0x00, 0x33, 0x33)     # PORCTRL
        self._cmd(0xB7, 0x35)                             # GCTRL
        self._cmd(0xBB, 0x19)                             # VCOMS
        self._cmd(0xC0, 0x2C)                             # LCMCTRL
        self._cmd(0xC2, 0x01)                             # VDVVRHEN
        self._cmd(0xC3, 0x12)                             # VRHS
        self._cmd(0xC4, 0x20)                             # VDVS
        self._cmd(0xC6, 0x0F)                             # FRCTRL2 60Hz
        self._cmd(0xD0, 0xA4, 0xA1)                       # PWCTRL1
        self._cmd(0xE0, 0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B,
                        0x3F, 0x54, 0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23)
        self._cmd(0xE1, 0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C,
                        0x3F, 0x44, 0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23)
        self._cmd(0x21)                                   # INVON
        self._cmd(0x29)                                   # DISPON
        self.blk.set_value(1)

    def set_window(self, x0, y0, x1, y1):
        x0 += self.x_offset; x1 += self.x_offset
        y0 += self.y_offset; y1 += self.y_offset
        self._cmd(0x2A, x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)
        self._cmd(0x2B, y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)
        self._cmd(0x2C)

    def fill(self, color565):
        self.set_window(0, 0, WIDTH - 1, HEIGHT - 1)
        hi = (color565 >> 8) & 0xFF
        lo = color565 & 0xFF
        row = bytes([hi, lo]) * WIDTH
        self._data_bytes(row * HEIGHT)

    def blit_rgb565(self, buf):
        assert len(buf) == WIDTH * HEIGHT * 2
        self.set_window(0, 0, WIDTH - 1, HEIGHT - 1)
        self._data_bytes(buf)

    def close(self):
        self.blk.set_value(0)
        self.spi.close()


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def color_bars(disp):
    bars = [
        rgb565(255, 0, 0),
        rgb565(0, 255, 0),
        rgb565(0, 0, 255),
        rgb565(255, 255, 0),
        rgb565(0, 255, 255),
        rgb565(255, 0, 255),
        rgb565(255, 255, 255),
    ]
    rows_per_bar = HEIGHT // len(bars)
    buf = bytearray()
    for i in range(HEIGHT):
        idx = min(i // rows_per_bar, len(bars) - 1)
        c = bars[idx]
        hi, lo = (c >> 8) & 0xFF, c & 0xFF
        buf.extend(bytes([hi, lo]) * WIDTH)
    disp.blit_rgb565(bytes(buf))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["bars", "red", "green", "blue", "white", "black"],
                   default="bars")
    p.add_argument("--hz", type=int, default=40_000_000)
    p.add_argument("--xoff", type=int, default=0)
    p.add_argument("--yoff", type=int, default=20)
    args = p.parse_args()

    disp = ST7789(hz=args.hz, x_offset=args.xoff, y_offset=args.yoff)
    try:
        disp.init()
        if args.mode == "bars":
            color_bars(disp)
        else:
            disp.fill({"red": rgb565(255, 0, 0),
                       "green": rgb565(0, 255, 0),
                       "blue": rgb565(0, 0, 255),
                       "white": rgb565(255, 255, 255),
                       "black": 0}[args.mode])
        print(f"done: mode={args.mode}, hz={args.hz}, "
              f"offset=({args.xoff},{args.yoff})")
    finally:
        # leave backlight on so we can see the result; CS released on exit
        pass


if __name__ == "__main__":
    main()
