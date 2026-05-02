#!/usr/bin/env python3
"""System telemetry HUD for 240x280 ST7789V2 LCD — SpaceX-inspired.

Aesthetic translation of `docs/design/DESIGN-spacex.md` to a 240x280 surface.
SpaceX's web presence is photographic minimalism; their *Falcon launch
streams* are dense engineering HUDs. Both share one DNA: pure black canvas,
spectral-white type, all-uppercase positive-tracked DIN-flavored type, zero
decorative chrome. This surface adopts the **launch-stream HUD** dialect to
fit the request for high information density.

Dialect rules:

  - Pure black (#000000) canvas, full-bleed; no cards/panels/containers.
  - Spectral White (#f0f0fa) — single text color (slight blue-violet tint).
  - All-uppercase, positive letter-spacing (simulated via tracked spaces).
  - DejaVu Sans Mono Bold = D-DIN substitute (geometric, industrial).
  - Bars are filled in spectral white; tracks are 12% spectral.
  - Hairlines (~12% spectral) are the only divider. No shadows, no fills.
  - Numbered section labels ("01 CPU", "02 MEM") = mission-briefing voice.
  - Bottom telemetry strip mimics readout console: load avg + net counters.

Data surfaced:
  - 8-core CPU per-core bars (4×A55 LITTLE | 4×A78 big) + overall %
  - RAM used / total + percent bar
  - 6 thermal zones (CPL/CPB/GPU/NPU/DDR/SKN) as vertical bars + numeric
  - 60-sample sparkline of CPU big temp
  - 1m/5m/15m load average, RX/TX byte rate, uptime (T+ counter)
"""

from __future__ import annotations

import argparse
import glob
import os
import time
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from st7789 import HEIGHT, WIDTH, ST7789

# --- SpaceX tokens ---
SPACE_BLACK    = (0x00, 0x00, 0x00)
SPECTRAL_WHITE = (0xf0, 0xf0, 0xfa)
HAIRLINE       = (0x2a, 0x2a, 0x32)   # ~12% spectral on black
GHOST          = (0x55, 0x55, 0x60)   # ~33% spectral — muted UI
DIM            = (0x90, 0x90, 0x9c)   # ~57% — secondary readouts

SS = 2  # supersample for clean curves + small text

_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    p = Path(_FONT_DIR) / name
    if p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def f_mono(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """DejaVu Sans Mono — D-DIN substitute (geometric + industrial)."""
    return _font("DejaVuSansMono-Bold.ttf" if bold
                 else "DejaVuSansMono.ttf", size)


def f_sans(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return _font("DejaVuSans-Bold.ttf" if bold
                 else "DejaVuSans.ttf", size)


# --- letter-spacing helper (PIL has no native tracking) ---

def tracked(s: str, spaces: int = 1) -> str:
    """Insert N spaces between every character to simulate +tracking."""
    sep = " " * spaces
    return sep.join(s)


def text_w(d: ImageDraw.ImageDraw, s: str,
           f: ImageFont.FreeTypeFont) -> float:
    return d.textlength(s, font=f)


# --- HUD primitives ---

def hairline(d: ImageDraw.ImageDraw, y: int, x0: int = 0, x1: int = WIDTH,
             color: tuple = HAIRLINE) -> None:
    d.line([(x0 * SS, y * SS), (x1 * SS, y * SS)], fill=color, width=1 * SS)


def hbar(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int,
         pct: float, fill: tuple = SPECTRAL_WHITE,
         track: tuple = HAIRLINE) -> None:
    """Horizontal progress bar."""
    d.rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS), fill=track)
    if pct > 0.5:
        w = (x1 - x0) * min(pct, 100) / 100
        d.rectangle((x0 * SS, y0 * SS, (x0 + w) * SS, y1 * SS), fill=fill)


def vbar(d: ImageDraw.ImageDraw, cx: float, y_base: int, max_h: int,
         pct: float, w: int = 6, fill: tuple = SPECTRAL_WHITE,
         track: tuple = HAIRLINE) -> None:
    """Vertical bar grown from y_base upwards."""
    h = max_h * min(pct, 100) / 100
    x0 = (cx - w / 2) * SS
    x1 = (cx + w / 2) * SS
    # full-height track
    d.rectangle((x0, (y_base - max_h) * SS, x1, y_base * SS),
                fill=track)
    if h > 0.5:
        d.rectangle((x0, (y_base - h) * SS, x1, y_base * SS), fill=fill)


def sparkline(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
              samples: list[float], color: tuple = SPECTRAL_WHITE) -> None:
    if len(samples) < 2:
        return
    lo, hi = min(samples), max(samples)
    span = max(1.0, hi - lo)
    pts = []
    for i, v in enumerate(samples):
        px = (x + (i / (len(samples) - 1)) * w) * SS
        py = (y + h - ((v - lo) / span) * h) * SS
        pts.append((px, py))
    d.line(pts, fill=color, width=1 * SS)
    # tip marker
    last_x, last_y = pts[-1]
    d.rectangle((last_x - 1 * SS, last_y - 1 * SS,
                 last_x + 1 * SS, last_y + 1 * SS), fill=color)


# =====================================================================
# Layout — 240×280, divided into 6 zones by hairline
# =====================================================================

def render(state: dict) -> Image.Image:
    W, H = WIDTH * SS, HEIGHT * SS
    img = Image.new("RGB", (W, H), SPACE_BLACK)
    d = ImageDraw.Draw(img)

    # ---------------- 1. TOP STATUS BAR (y 0..16) ----------------
    f_top = f_mono(8 * SS)
    left = "FLANGE/A7Z"
    right = f"T+ {fmt_uptime(state['uptime'])}"
    d.text((6 * SS, 4 * SS), left, font=f_top, fill=SPECTRAL_WHITE)
    rw = text_w(d, right, f_top)
    d.text((W - rw - 6 * SS, 4 * SS), right, font=f_top, fill=SPECTRAL_WHITE)
    hairline(d, 16)

    # ---------------- 2. CPU BLOCK (y 18..56) ----------------
    f_section = f_mono(9 * SS)
    f_big = f_mono(20 * SS)
    f_micro = f_mono(7 * SS)

    d.text((6 * SS, 22 * SS), "01 CPU", font=f_section, fill=SPECTRAL_WHITE)
    big = f"{int(round(state['cpu_overall'])):03d}%"
    bw = text_w(d, big, f_big)
    d.text((W - bw - 6 * SS, 19 * SS), big, font=f_big, fill=SPECTRAL_WHITE)

    # 8 core mini-bars: cpu0..3 (LITTLE) | cpu4..7 (big)
    cores = state["cpu_cores"]
    bar_y_base = 56
    bar_max_h = 14
    bar_w = 6
    # spread 8 bars across 156px width on the left, leaving room for "%"
    x_left = 8
    x_right = 168
    n = len(cores)
    if n > 0:
        gap = (x_right - x_left) / n
        for i, pct in enumerate(cores):
            cx = x_left + gap * (i + 0.5)
            vbar(d, cx, bar_y_base, bar_max_h, pct, w=bar_w)
        # cluster label between LITTLE/big (after 4th core if n=8)
        if n == 8:
            split_x = x_left + gap * 4
            d.line([(split_x * SS, (bar_y_base - bar_max_h - 1) * SS),
                    (split_x * SS, (bar_y_base + 1) * SS)],
                   fill=GHOST, width=1 * SS)
            d.text((x_left * SS + 2, (bar_y_base + 2) * SS),
                   "4×A55", font=f_micro, fill=DIM)
            d.text((split_x * SS + 4, (bar_y_base + 2) * SS),
                   "4×A78", font=f_micro, fill=DIM)

    hairline(d, 64)

    # ---------------- 3. MEM BLOCK (y 66..96) ----------------
    d.text((6 * SS, 70 * SS), "02 MEM", font=f_section, fill=SPECTRAL_WHITE)
    mem_pct = state["mem_pct"]
    used_gb = state["mem_used"] / 1024 / 1024
    total_gb = state["mem_total"] / 1024 / 1024
    mem_str = f"{used_gb:.1f}/{total_gb:.1f} GB"
    mw = text_w(d, mem_str, f_section)
    d.text((W - mw - 6 * SS, 70 * SS), mem_str, font=f_section,
           fill=SPECTRAL_WHITE)

    hbar(d, 6, 84, 200, 89, mem_pct)
    pct_str = f"{int(round(mem_pct))}%"
    pw = text_w(d, pct_str, f_section)
    d.text((W - pw - 6 * SS, 82 * SS), pct_str, font=f_section,
           fill=SPECTRAL_WHITE)
    hairline(d, 98)

    # ---------------- 4. THERMAL BLOCK (y 100..168) ----------------
    d.text((6 * SS, 104 * SS), "03 THRM", font=f_section,
           fill=SPECTRAL_WHITE)
    temps = state["temps"]  # list[(label, temp_c)]
    if temps:
        max_t = max(t for _, t in temps)
        max_label = next(lbl for lbl, t in temps if t == max_t)
        max_str = f"MAX {int(round(max_t))}°{max_label}"
        mw = text_w(d, max_str, f_section)
        d.text((W - mw - 6 * SS, 104 * SS), max_str, font=f_section,
               fill=SPECTRAL_WHITE)

        # vertical bars
        x_left = 12
        x_right = 228
        n = len(temps)
        gap = (x_right - x_left) / n
        bar_y_base = 144
        bar_max_h = 24
        # temp scale: 25..90°C maps to 0..100% bar height
        for i, (lbl, t) in enumerate(temps):
            cx = x_left + gap * (i + 0.5)
            pct = max(0, min(100, (t - 25) / 65 * 100))
            vbar(d, cx, bar_y_base, bar_max_h, pct, w=12)
            # label
            lw = text_w(d, lbl, f_micro)
            d.text((cx * SS - lw / 2, (bar_y_base + 2) * SS), lbl,
                   font=f_micro, fill=DIM)
            # value
            val = str(int(round(t)))
            vw = text_w(d, val, f_micro)
            d.text((cx * SS - vw / 2, (bar_y_base + 11) * SS), val,
                   font=f_micro, fill=SPECTRAL_WHITE)
    hairline(d, 168)

    # ---------------- 5. SPARKLINE (y 170..220) ----------------
    d.text((6 * SS, 174 * SS), "04 HIST 60S", font=f_section,
           fill=SPECTRAL_WHITE)
    hist = state["temp_history"]
    if len(hist) >= 2:
        hi = max(hist); lo = min(hist)
        scale_str = f"{int(round(lo))}-{int(round(hi))}°"
        sw = text_w(d, scale_str, f_section)
        d.text((W - sw - 6 * SS, 174 * SS), scale_str, font=f_section,
               fill=DIM)
    sparkline(d, 6, 188, 228, 30, list(hist))
    hairline(d, 222)

    # ---------------- 6. FOOTER (y 224..278) ----------------
    f_foot = f_mono(8 * SS)
    f_foot_big = f_mono(9 * SS)
    la = state["loadavg"]
    load_str = f"LOAD {la[0]:.2f}  {la[1]:.2f}  {la[2]:.2f}"
    d.text((6 * SS, 230 * SS), load_str, font=f_foot_big,
           fill=SPECTRAL_WHITE)

    rxr, txr = state["net_rate"]   # bytes/sec
    iface = state["net_iface"]
    net_str = f"NET ▲{fmt_rate(txr)}  ▼{fmt_rate(rxr)}"
    d.text((6 * SS, 246 * SS), net_str, font=f_foot_big,
           fill=SPECTRAL_WHITE)
    if iface:
        if_str = f"IF {iface[:8]}"
        iw = text_w(d, if_str, f_foot)
        d.text((W - iw - 6 * SS, 247 * SS), if_str, font=f_foot, fill=DIM)

    # bottom heartbeat: scrolling tick row
    tick = state["tick"]
    seg_w = 3
    n_segs = WIDTH // (seg_w + 1)
    y_tick = 268
    for i in range(n_segs):
        x = i * (seg_w + 1)
        on = (i <= (tick % n_segs))
        c = SPECTRAL_WHITE if on else HAIRLINE
        d.rectangle((x * SS, y_tick * SS,
                     (x + seg_w) * SS, (y_tick + 2) * SS), fill=c)

    return img.resize((WIDTH, HEIGHT), Image.LANCZOS)


# =====================================================================
# Sensors
# =====================================================================

def fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_rate(bps: float) -> str:
    """Format bytes/sec as <unit>K / <unit>M with 1 decimal."""
    if bps < 1024:
        return f"{int(bps):3d}B"
    if bps < 1024 * 1024:
        return f"{bps / 1024:4.1f}K"
    return f"{bps / 1024 / 1024:4.1f}M"


def cpu_sample_all() -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    with open("/proc/stat") as f:
        for line in f:
            if not line.startswith("cpu"):
                break
            parts = line.split()
            name = parts[0]
            fields = list(map(int, parts[1:]))
            idle = fields[3] + fields[4]
            total = sum(fields)
            out[name] = (idle, total)
    return out


def cpu_pcts(prev: dict, cur: dict) -> tuple[float, list[float]]:
    overall = 0.0
    cores: list[tuple[int, float]] = []
    for name, (idle, total) in cur.items():
        if name not in prev:
            continue
        p_idle, p_total = prev[name]
        di = idle - p_idle
        dt = total - p_total
        pct = max(0.0, (1.0 - di / dt) * 100) if dt > 0 else 0.0
        if name == "cpu":
            overall = pct
        else:
            try:
                idx = int(name[3:])
                cores.append((idx, pct))
            except ValueError:
                pass
    cores.sort()
    return overall, [pct for _, pct in cores]


def mem_info() -> tuple[int, int, float]:
    info: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, rest = line.partition(":")
            info[k.strip()] = int(rest.split()[0])
    total = info["MemTotal"]
    avail = info.get("MemAvailable",
                     info["MemFree"] + info.get("Buffers", 0)
                     + info.get("Cached", 0))
    used = total - avail
    return used, total, (1.0 - avail / total) * 100


# Map verbose thermal_zone "type" strings to compact 3-letter HUD labels.
_THERMAL_LABELS = {
    "cpul_thermal_zone": "CPL",
    "cpub_thermal_zone": "CPB",
    "gpu_thermal_zone": "GPU",
    "npu_thermal_zone": "NPU",
    "ddr_thermal_zone": "DDR",
    "skin_zone": "SKN",
}


def thermals() -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for type_path in sorted(glob.glob("/sys/class/thermal/thermal_zone*/type")):
        try:
            with open(type_path) as f:
                ttype = f.read().strip()
            if ttype not in _THERMAL_LABELS:
                continue
            temp_path = type_path.replace("/type", "/temp")
            with open(temp_path) as f:
                v = int(f.read().strip())
            t = v / 1000.0 if v > 1000 else float(v)
            out.append((_THERMAL_LABELS[ttype], t))
        except (OSError, ValueError):
            continue
    # Stable ordering matching label pool
    order = ["CPL", "CPB", "GPU", "NPU", "DDR", "SKN"]
    out.sort(key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    return out


def loadavg() -> tuple[float, float, float]:
    with open("/proc/loadavg") as f:
        a, b, c, *_ = f.read().split()
    return float(a), float(b), float(c)


def uptime() -> float:
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def net_sample() -> tuple[int, int, str | None]:
    rx = tx = 0
    busiest = None
    busiest_bytes = -1
    with open("/proc/net/dev") as f:
        for line in f:
            if ":" not in line:
                continue
            iface, _, rest = line.partition(":")
            iface = iface.strip()
            if iface == "lo" or iface.startswith("sit"):
                continue
            fields = rest.split()
            r = int(fields[0])
            t = int(fields[8])
            rx += r
            tx += t
            if r + t > busiest_bytes:
                busiest_bytes = r + t
                busiest = iface
    return rx, tx, busiest


# =====================================================================
# Main loop
# =====================================================================

def collect(prev_cpu: dict, prev_net: tuple[int, int, str | None],
            history: deque, dt: float, tick: int) -> tuple[dict, dict, tuple]:
    cur_cpu = cpu_sample_all()
    overall, cores = cpu_pcts(prev_cpu, cur_cpu)
    used, total, mpct = mem_info()
    temps = thermals()
    cur_net = net_sample()
    prx, ptx, _ = prev_net
    rx, tx, iface = cur_net
    if dt > 0 and prx >= 0:
        rxr = max(0, (rx - prx) / dt)
        txr = max(0, (tx - ptx) / dt)
    else:
        rxr = txr = 0.0

    # Track CPU big temp (or fall back to highest cpu zone) for sparkline.
    spark_t = next((t for lbl, t in temps if lbl == "CPB"),
                   next((t for lbl, t in temps if lbl == "CPL"), 0.0))
    history.append(spark_t)

    state = {
        "uptime": uptime(),
        "cpu_overall": overall,
        "cpu_cores": cores,
        "mem_used": used,
        "mem_total": total,
        "mem_pct": mpct,
        "temps": temps,
        "temp_history": history,
        "loadavg": loadavg(),
        "net_rate": (rxr, txr),
        "net_iface": iface,
        "tick": tick,
    }
    return state, cur_cpu, cur_net


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--save", help="write preview PNG and exit")
    args = p.parse_args()

    history: deque = deque(maxlen=60)

    if args.save:
        # synthetic data for offline preview
        history.extend([55, 56, 56, 57, 58, 60, 61, 62, 63, 62, 61, 60,
                        59, 58, 58, 59, 60, 61, 62, 62, 63, 64, 65, 64,
                        63, 62, 61, 60, 60, 59])
        state = {
            "uptime": 3424.75,
            "cpu_overall": 42,
            "cpu_cores": [62, 41, 35, 28, 75, 64, 52, 38],
            "mem_used": int(1.4 * 1024 * 1024),
            "mem_total": int(4.0 * 1024 * 1024),
            "mem_pct": 35,
            "temps": [("CPL", 58), ("CPB", 62), ("GPU", 41),
                      ("NPU", 39), ("DDR", 53), ("SKN", 31)],
            "temp_history": history,
            "loadavg": (0.04, 0.06, 0.03),
            "net_rate": (1280, 410),
            "net_iface": "wlxf4ab5c",
            "tick": 17,
        }
        img = render(state)
        img.save(args.save)
        print(f"saved -> {args.save}")
        return

    disp = ST7789()
    disp.init()
    prev_cpu = cpu_sample_all()
    prev_net = net_sample()
    last_t = time.time()
    tick = 0
    time.sleep(0.2)

    try:
        while True:
            now = time.time()
            dt = max(1e-3, now - last_t)
            last_t = now
            state, prev_cpu, prev_net = collect(prev_cpu, prev_net,
                                                 history, dt, tick)
            img = render(state)
            buf = image_to_rgb565(img)
            disp.blit_rgb565(buf)
            if args.once:
                break
            tick += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


def image_to_rgb565(img: Image.Image) -> bytes:
    arr = np.asarray(img, dtype=np.uint16)
    r = (arr[..., 0] >> 3) & 0x1F
    g = (arr[..., 1] >> 2) & 0x3F
    b = (arr[..., 2] >> 3) & 0x1F
    rgb = (r << 11) | (g << 5) | b
    out = np.empty((arr.shape[0], arr.shape[1], 2), dtype=np.uint8)
    out[..., 0] = (rgb >> 8) & 0xFF
    out[..., 1] = rgb & 0xFF
    return out.tobytes()


if __name__ == "__main__":
    main()
