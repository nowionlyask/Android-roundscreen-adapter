"""手表远程控制：通过 ADB over IPv6 操作 OPPO Watch X。

给手表 App 和浏览器用的中转层。

提供的操作：
- 改 DPI、恢复 DPI
- 模拟点击（按坐标或按点位名字）
- 截图
- 读写点位配置
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from pathlib import Path

log = logging.getLogger("biliauto.watchctl")

# 手表的 ADB 地址。
# 蜂窝网络的 IPv6 是动态分配的，会变 —— 所以这里是个可变的全局变量，
# 由 learn_watch_ip() 在手表访问服务器时自动校正。
WATCH_ADDR = "[YOUR_WATCH_IPV6]:5555"
DEFAULT_DPI = 120

_lock = threading.Lock()
# 最近一次自动学习的地址，避免同一次访问里反复触发重连
_last_learned = ""


def learn_watch_ip(ip: str) -> None:
    """用手表访问服务器时的来源 IP，自动更新 ADB 目标地址。

    手表每次打开 App 都会请求服务器，这时候的源地址就是它当前的地址。
    如果和记录的不一致，说明 IPv6 变了，这里自动改正并重连。
    """
    global WATCH_ADDR, _last_learned

    if not ip or ip.startswith(("127.", "::1", "::ffff:127.")):
        return

    # 本地网段的 IPv6 不太可能是手表的可路由地址，跳过
    if ip.startswith(("fe80", "fd", "fc")):
        return

    new_addr = f"[{ip}]:5555"
    if new_addr == WATCH_ADDR:
        return
    if new_addr == _last_learned:
        return

    old = WATCH_ADDR
    WATCH_ADDR = new_addr
    _last_learned = new_addr
    log.info("手表地址更新: %s -> %s（来源自动学习）", old, new_addr)

    # 后台重连，不阻塞当前请求
    def _reconnect() -> None:
        try:
            subprocess.run(["adb", "disconnect", old],
                           capture_output=True, timeout=5)
            subprocess.run(["adb", "connect", new_addr],
                           capture_output=True, timeout=8)
            log.info("已重新连接 %s", new_addr)
        except Exception:  # noqa: BLE001
            log.debug("自动重连失败", exc_info=True)

    threading.Thread(target=_reconnect, daemon=True).start()


def _adb(*args: str, timeout: int = 20) -> tuple[int, str]:
    with _lock:
        try:
            # 每次都读最新的 WATCH_ADDR（可能被 learn_watch_ip 改过）
            addr = globals()["WATCH_ADDR"]
            r = subprocess.run(["adb", "-s", addr, *args],
                               capture_output=True, text=True, timeout=timeout)
            return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
        except subprocess.TimeoutExpired:
            return 1, "adb 超时"
        except Exception as e:  # noqa: BLE001
            return 1, f"{type(e).__name__}: {e}"


def ensure_connected() -> bool:
    """确保 adb 连着手表。断了就重连。

    超时设得比较短：手表可能通过 USB 连接而不是 WiFi，
    这时 adb connect 会一直等到超时，拖慢整个请求。
    """
    code, out = _adb("get-state", timeout=4)
    if code == 0 and "device" in out:
        return True

    # 尝试重连（短超时，避免卡住调用方）
    try:
        subprocess.run(["adb", "connect", WATCH_ADDR],
                       capture_output=True, timeout=6)
    except subprocess.TimeoutExpired:
        log.debug("adb connect 超时: %s", WATCH_ADDR)

    code, out = _adb("get-state", timeout=4)
    return code == 0 and "device" in out


def current_density() -> int | None:
    code, out = _adb("shell", "wm", "density")
    if code != 0:
        return None
    m = re.search(r"Override density:\s*(\d+)", out)
    if m:
        return int(m.group(1))
    m = re.search(r"Physical density:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def set_density(value: int | None) -> tuple[bool, int | None]:
    """value=None 表示恢复默认。"""
    if value is None:
        _adb("shell", "wm", "density", "reset")
    else:
        value = max(80, min(640, int(value)))
        _adb("shell", "wm", "density", str(value))
    return True, current_density()


def tap(x: int, y: int) -> tuple[bool, str]:
    """注入点击。

    这里必须自己判断成败：`adb -s xxx shell ...` 在设备不存在时，
    有些 adb 版本仍返回 0，只是往 stderr 打一句 not found。
    不检查的话就会出现"接口返回 200 但什么都没点"的假成功。
    """
    if not ensure_connected():
        return False, f"手表未连接（{WATCH_ADDR}），无法注入点击"
    code, out = _adb("shell", "input", "tap", str(int(x)), str(int(y)))
    if "not found" in out.lower() or "error" in out.lower():
        return False, out
    return code == 0, out


def tap_key(keycode: int) -> tuple[bool, str]:
    code, out = _adb("shell", "input", "keyevent", str(int(keycode)))
    return code == 0, out


def swipe(x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> tuple[bool, str]:
    code, out = _adb("shell", "input", "swipe",
                     str(x1), str(y1), str(x2), str(y2), str(ms))
    return code == 0, out


def screenshot_bytes() -> bytes | None:
    with _lock:
        try:
            r = subprocess.run(["adb", "-s", WATCH_ADDR, "exec-out",
                                "screencap", "-p"],
                               capture_output=True, timeout=25)
            if r.returncode == 0 and r.stdout[:4] == b"\x89PNG":
                return r.stdout
            return None
        except Exception:  # noqa: BLE001
            return None


def app_info() -> dict:
    """当前前台应用。"""
    code, out = _adb("shell", "dumpsys activity activities")
    m = re.search(r"mResumedActivity.*?u0\s+([\w.]+)/([\w.$]+)", out)
    if m:
        return {"package": m.group(1), "activity": m.group(2)}
    return {}


def launch_app(package: str) -> tuple[bool, str]:
    """启动一个 App。"""
    code, out = _adb("shell", "monkey", "-p", package,
                     "-c", "android.intent.category.LAUNCHER", "1")
    if "No activities found" in out:
        # 退化：直接解析入口
        code2, out2 = _adb("shell", "cmd", "package", "resolve-activity",
                           "--brief", package)
        m = re.search(r"([\w.]+/[\w.$]+)", out2)
        if m:
            code, out = _adb("shell", "am", "start", "-n", m.group(1))
    return code == 0, out


def key_back() -> tuple[bool, str]:
    return tap_key(4)


def key_home() -> tuple[bool, str]:
    return tap_key(3)


# ---------- 点位配置 ----------

POINTS_FILE = Path("/home/hina/.config/biliauto/watch_points.json")


def load_points() -> dict:
    """读取点位配置。结构：
    {
      "global": [{name,x,y}],           # 所有应用通用的
      "apps": {"com.tencent.mobileqq": [{name,x,y}]}
    }
    """
    if not POINTS_FILE.exists():
        return {"global": [], "apps": {}}
    try:
        d = json.loads(POINTS_FILE.read_text(encoding="utf-8"))
        if isinstance(d, list):          # 兼容旧的扁平格式
            return {"global": d, "apps": {}}
        d.setdefault("global", [])
        d.setdefault("apps", {})
        return d
    except Exception:  # noqa: BLE001
        return {"global": [], "apps": {}}


def save_points(data: dict) -> bool:
    try:
        POINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        POINTS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        log.exception("保存点位失败")
        return False


def points_for_app(package: str) -> list[dict]:
    """某 App 该显示的按钮：通用 + 该应用专属。"""
    d = load_points()
    out = list(d.get("global") or [])
    out.extend((d.get("apps") or {}).get(package) or [])
    return out


def status() -> dict:
    """给 App 和浏览器用的完整状态。

    注意：**点位数据不依赖 ADB 连接**。
    手表可能通过 USB 而不是 WiFi 连接，或者暂时掉线，
    这时候 App 仍然需要拿到点位渲染悬浮按钮。
    所以 ADB 相关的字段探测失败时降级返回，不抛错、不阻塞。
    """
    # 点位和输入法列表纯粹读文件/本地配置，永远可用
    out = {
        "ok": True,
        "connected": False,
        "density": None,
        "default_dpi": DEFAULT_DPI,
        "front": {},
        "points": load_points(),
    }

    # ADB 探测可能很慢（连不上要等超时），失败就降级
    try:
        if ensure_connected():
            out["connected"] = True
            out["density"] = current_density()
            out["front"] = app_info() or {}
    except Exception:  # noqa: BLE001
        log.debug("ADB 探测失败，点位仍照常返回", exc_info=True)

    return out


# ---------- 输入法 ----------

def _sh(cmd: str) -> str:
    code, out = _adb("shell", cmd)
    return out


def ime_status() -> dict:
    """当前输入法状态。"""
    cur = _sh("settings get secure default_input_method").strip()
    enabled = _sh("settings get secure enabled_input_methods").strip()
    raw = _sh("ime list -a -s")
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        pkg = line.split("/")[0]
        label = pkg
        if "sogou" in pkg:
            label = "搜狗输入法"
        elif "iflytek" in pkg:
            label = "讯飞输入法"
        elif "baidu" in pkg:
            label = "百度输入法"
        items.append({
            "id": line,
            "package": pkg,
            "label": label,
            "active": line == cur,
        })
    return {
        "current": cur,
        "enabled": [x for x in enabled.split(":") if x],
        "available": items,
    }


def set_ime(ime_id: str) -> tuple[bool, str]:
    """切换默认输入法，并确保它在启用列表里。"""
    st = ime_status()
    enabled = st["enabled"]
    if ime_id not in enabled:
        enabled.append(ime_id)
        _sh("settings put secure enabled_input_methods "
            + ":".join(enabled))
    # 启用再设默认
    _sh(f"ime enable {ime_id}")
    code, out = _adb("shell", "ime", "set", ime_id)
    return code == 0, out or "ok"


def rollback_info() -> dict | None:
    """读取备份的原始状态。"""
    p = Path("/home/hina/.config/biliauto/watch_rollback.txt")
    if not p.exists():
        return None
    d = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            d[k.strip()] = v.strip()
    return d
