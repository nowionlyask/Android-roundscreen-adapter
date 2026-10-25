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
import os
import re
import subprocess
import threading
from pathlib import Path

log = logging.getLogger("biliauto.watchctl")

# ================================================================
# ⚠️ 【必改】手表的 ADB 地址
#
# 这是**手表**的 IP，不是服务器的。
# IPv6 要加方括号，局域网 IP 不用（但端口必须写 :5555）
#   例： "[2408:8478:xxx:xxxx::1]:5555"
#        "192.168.1.50:5555"
#
# 获取方法：
#   手表 USB 连着时执行： adb shell ip -6 addr show | grep inet6
#   然后在手表上开启网络调试： adb tcpip 5555
#
# 也可以用环境变量覆盖，不用改代码：
#   export WATCH_ADDR="192.168.1.50:5555"
# ================================================================
WATCH_ADDR = os.environ.get("WATCH_ADDR", "[WATCH_IPV6]:5555")
DEFAULT_DPI = 120

_lock = threading.Lock()


def _adb(*args: str, timeout: int = 20) -> tuple[int, str]:
    with _lock:
        try:
            r = subprocess.run(["adb", "-s", WATCH_ADDR, *args],
                               capture_output=True, text=True, timeout=timeout)
            return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
        except subprocess.TimeoutExpired:
            return 1, "adb 超时"
        except Exception as e:  # noqa: BLE001
            return 1, f"{type(e).__name__}: {e}"


def ensure_connected() -> bool:
    """确保 adb 连着手表。断了就重连。"""
    code, out = _adb("get-state", timeout=8)
    if code == 0 and "device" in out:
        return True
    # 尝试重连
    subprocess.run(["adb", "connect", WATCH_ADDR],
                   capture_output=True, timeout=20)
    code, out = _adb("get-state", timeout=8)
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
    code, out = _adb("shell", "input", "tap", str(int(x)), str(int(y)))
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
    """给 App 和浏览器用的完整状态。"""
    if not ensure_connected():
        return {"ok": False, "error": "adb 未连接手表"}
    cur = current_density()
    return {
        "ok": True,
        "connected": True,
        "density": cur,
        "default_dpi": DEFAULT_DPI,
        "front": app_info(),
        "points": load_points(),
        "ime": ime_status(),
    }


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
