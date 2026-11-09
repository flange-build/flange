#!/usr/bin/python3
"""usbmoded 实板验证：race-checklist 13 项竞态 + adbd×systemd×FFS + 并发。

对应 openspec/changes/add-usb-mode-switching 的 tasks 8.1 / 8.3 / 8.8。

**需要真实硬件，必须以 root 在目标板上运行**，不被 pytest 收集。
tests/test_usbmoded.py 是宿主机上的伪 configfs 单元测试，两者不可互相替代：
伪树模拟不了 configfs 的内核语义，也模拟不了 role 切换的异步性。

用法：
    scp tests/usbmoded_field_verify.py <board>:/tmp/
    ssh <board> sudo python3 /tmp/usbmoded_field_verify.py

首次在新板子上运行前请确认有带外通道（串口，或 SSH over 网络）——
本脚本会反复切换场景、解绑 UDC、kill adbd，期间 adb 通道会中断。

换板子时调整下面两个常量。
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

# —— 按板子调整 ——
GADGET_GROUP = "rockchip"      # 对应 /etc/usbmode/gadget.d/ 的 gadget.group
UDC_NAME = "fc000000.usb"      # ls /sys/class/udc/

sys.path.insert(0, "/usr/lib/python3/dist-packages")
from usbmoded import capabilities, configfs, udc  # noqa: E402
from usbmoded.capabilities.adb import _endpoint_is_open  # noqa: E402
from usbmoded.capability import sort_by_kernel_order  # noqa: E402
from usbmoded.gadget import Gadget, GadgetDescriptor  # noqa: E402

G = Path("/sys/kernel/config/usb_gadget") / GADGET_GROUP
results: list[tuple[str, bool]] = []


def check(tag: str, name: str, ok: bool, detail: str = "") -> None:
    results.append((tag, ok))
    print(f"  {'✓' if ok else '✗'} {tag} {name}" + (f" — {detail}" if detail else ""))


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def links() -> set[str]:
    return {p.name for p in (G / "configs/b.1").iterdir() if p.name.startswith("f-")}


def scene(name: str) -> None:
    subprocess.run(f"usb-mode set {name}", shell=True, capture_output=True)
    time.sleep(4)


def adbd_count() -> int:
    out = sh("pidof adbd")
    return len(out.split()) if out else 0


def settle(sec: float = 3.0) -> None:
    """给硬件留出状态稳定的时间。

    UDC 绑定、role 切换、枚举都是异步的，紧接着断言会读到中间态。
    """
    time.sleep(sec)


scene("debug")
print("=== 基线 ===")
print(f"  configs={sorted(links())} adbd={adbd_count()} UDC=[{configfs.read_attr(G/'UDC')}]")
print()

# ---- #6 幂等写
attr = G / "idVendor"
before = configfs.read_attr(attr)
wrote = configfs.write_attr(attr, before)
check("6", "幂等写：值相同时跳过写入", wrote is False, f"idVendor={before}")

# ---- #7 idProduct 仅在 UDC 未绑定时写
desc = GadgetDescriptor(group="rockchip", vendor_id="0x2207", product_name="x",
                        manufacturer="y", pid_map={"adb": "0x0006", "mtp": "0x0001",
                                                   "default": "0x0019"})
g = Gadget(desc)
pid_before = configfs.read_attr(G / "idProduct")
bound = bool(udc.current_binding(G))
g.sync_product_id(["mtp"])          # 若不守卫会写成 0x0001
pid_after = configfs.read_attr(G / "idProduct")
check("7", "idProduct 仅在 UDC 未绑定时写",
      bound and pid_before == pid_after,
      f"UDC已绑定={bound} {pid_before}→{pid_after}（守卫生效则不变）")

# ---- #2 UDC 绑定回读校验
real_write = configfs.write_attr
def swallow(path, value):           # 模拟内核吞掉写入
    if path.name == "UDC":
        path.write_text("\n")
        return True
    return real_write(path, value)
configfs.write_attr = swallow
try:
    udc.bind(G, udc.Udc(UDC_NAME))
    check("2", "UDC 绑定回读校验", False, "写入被吞却未报错")
except udc.UdcError as exc:
    check("2", "UDC 绑定回读校验", UDC_NAME in str(exc), "写入被吞时正确报错")
finally:
    configfs.write_attr = real_write
    udc.bind(G, udc.Udc(UDC_NAME))   # 恢复绑定
    settle(2)

# ---- #3 枚举状态校验 / #5 无主机连接识别
controller = udc.Udc(UDC_NAME)
state = controller.state
ok3 = state in (udc.UdcState.CONFIGURED, udc.UdcState.NOT_ATTACHED)
check("3", "枚举状态校验", ok3, f"state={state.value}")

accept, st = udc.verify_enumeration(controller)
check("5", "区分无主机连接与真实故障", accept,
      f"state={st.value} 判定为{'可接受' if accept else '故障'}")

# ---- #4 枚举恢复 bounce 不触碰 configfs/FFS
links_before = links()
mounted_before = "usb-ffs/adb" in sh("mount")
adbd_before = sh("pidof adbd")
udc.bounce_connection(controller)
settle(2)
check("4", "bounce 不触碰 ConfigFS/FFS",
      links() == links_before and ("usb-ffs/adb" in sh("mount")) == mounted_before
      and sh("pidof adbd") == adbd_before,
      f"links不变={links() == links_before} FFS挂载不变={('usb-ffs/adb' in sh('mount')) == mounted_before} adbd未重启={sh('pidof adbd') == adbd_before}")

# ---- #1 UDC 就绪等待
t0 = time.time()
found = udc.wait_for_udc()
check("1", "UDC 就绪等待", found is not None and found.name == UDC_NAME,
      f"{time.time()-t0:.3f}s 命中 {found.name if found else '(无)'}")

# ---- #12 内核要求的 function 排序
from usbmoded import capabilities                      # noqa: E402
from usbmoded.capability import sort_by_kernel_order   # noqa: E402
caps = capabilities.resolve(["ums", "adb", "ncm"])
order = [c.name for c in sort_by_kernel_order(caps)]
check("12", "能力按内核顺序排列", order == ["ncm", "adb", "ums"], f"{order}")

# ---- #13 启动幂等守卫：重复 reload 不重配
adbd_before = sh("pidof adbd")
mark = int(time.time())
for _ in range(5):
    subprocess.run("systemctl reload usbmoded.service", shell=True, capture_output=True)
time.sleep(5)
logs = sh(f"journalctl -u usbmoded.service --since @{mark} --no-pager -o cat")
check("#13", "重复 reload 被幂等守卫短路",
      sh("pidof adbd") == adbd_before and "已启用能力" not in logs,
      f"adbd 未重启={sh('pidof adbd') == adbd_before}，日志无重配记录")

# ---- #8 断连恢复不拆 ConfigFS（需先停服务，隔离它的自动恢复）
subprocess.run("systemctl stop usbmoded.service", shell=True, capture_output=True)
time.sleep(2)
before8, mounted8 = links(), "usb-ffs/adb" in sh("mount")
configfs.write_attr(G / "UDC", "")
time.sleep(1)
unbound = not (configfs.read_attr(G / "UDC") or "")
kept = links() == before8 and ("usb-ffs/adb" in sh("mount")) == mounted8
subprocess.run("systemctl start usbmoded.service", shell=True, capture_output=True)
time.sleep(8)
check("#8", "断连恢复保留 ConfigFS 链接",
      unbound and kept and links() == before8 and bool(configfs.read_attr(G / "UDC")),
      f"解绑生效={unbound} 链接全程保留={kept and links() == before8} "
      f"已重新绑定={bool(configfs.read_attr(G/'UDC'))}")

# ---- #9 能力变化先停后启
scene("debug")
mark = int(time.time())
scene("net")                                 # adb → adb+ncm
logs = sh(f"journalctl -u usbmoded.service --since @{mark} --no-pager -o cat")
has_change = "能力集合变化" in logs
ncm_on = "f-ncm.gs0" in links()
check("#9", "能力集合变化走先停后启", has_change and ncm_on,
      f"日志有'能力集合变化'={has_change} ncm已启用={ncm_on}")

# ---- #10 / 8.3 daemon 由 systemd 管理，反复启停不累积进程
counts = []
for _ in range(4):
    scene("debug")
    counts.append(adbd_count())
    scene("net")
    counts.append(adbd_count())
scene("debug")
counts.append(adbd_count())
check("#10", "反复启停 adbd 进程数不累积", max(counts) <= 1, f"各轮进程数={counts}")

# ---- 8.3 FFS endpoint 被实际打开（不是只看 inode 存在）
from usbmoded.capabilities.adb import _endpoint_is_open  # noqa: E402
ep = "/dev/usb-ffs/adb/ep1"
check("8.3", "adbd 实际持有 FFS endpoint fd", _endpoint_is_open(ep),
      f"{ep} 被进程打开={_endpoint_is_open(ep)}")

# ---- 8.3 adbd 被 kill 后由 systemd 自动拉起
old = sh("pidof adbd")
subprocess.run("systemctl kill --signal=SIGKILL usbmoded-adbd.service", shell=True, capture_output=True)
time.sleep(6)
new = sh("pidof adbd")
check("8.3", "adbd 被 kill 后 systemd 自动恢复",
      bool(new) and new != old and adbd_count() <= 1,
      f"{old} → {new}")

# ---- #11 / 8.8 并发：切换与 udev 式 reload 同时进行
errors = []
def spam_reload():
    for _ in range(12):
        subprocess.run("systemctl reload usbmoded.service", shell=True, capture_output=True)
        time.sleep(0.25)

t = threading.Thread(target=spam_reload, daemon=True)
t.start()
for s in ("net", "debug", "net", "debug"):
    r = subprocess.run(f"usb-mode set {s}", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        errors.append(f"{s}: {r.stderr.strip()[:60]}")
    time.sleep(2)
t.join()
time.sleep(5)
final_links = links()
final_udc = configfs.read_attr(G / "UDC")
check("#11/8.8", "并发切换与 reload 被串行化且状态一致",
      not errors and final_links == {"f-ffs.adb"} and bool(final_udc) and adbd_count() <= 1,
      f"错误={errors or '无'} configs={sorted(final_links)} UDC=[{final_udc}] adbd数={adbd_count()}")

print()
print("=" * 62)
passed = sum(1 for _, ok in results if ok)
for tag, ok in results:
    if not ok:
        print(f"  未通过: {tag}")
print(f"实板验证 {passed}/{len(results)} 通过")
sys.exit(0 if passed == len(results) else 1)
