#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手表点选工具 —— 在网页上点选位置，保存后自动同步到你的服务器。

用法：
    1. 填好配置（或启动时改好下方的 SERVER 配置）
    2. python serve.py
    3. 浏览器打开 http://127.0.0.1:8765

工作流程：
    网页上点选位置 → 记录点位 → 点「保存」→
    写入本地 points.json → 自动 POST 到服务器 /api/watch/points →
    手表 App 的悬浮窗刷新后就能看到新按钮。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ================================================================
# ⚠️ 配置：三种方式任选其一
#
#   1. 环境变量（推荐，见 env.sh.example）
#   2. 命令行参数（未实现）
#   3. 直接改下面的默认值
#
# 【必改】至少要把 BILIAUTO_SERVER 和 BILIAUTO_KEY 填对，否则同步不了。
# 详细说明见项目根目录的 SETUP.md
# ================================================================

# ADB 可执行文件路径。留空则用系统 PATH 里的 adb。
ADB = os.environ.get("ADB_PATH", "adb")

# 设备序列号。留空表示自动选第一台。
# 获取方法：adb devices
SERIAL = os.environ.get("ADB_SERIAL", "")

# 【必改】目标服务器地址（运行中转服务的机器）
#   IPv6： https://[2408:8207:1234:5678::1]:8788
#   局域网：https://192.168.1.100:8788
SERVER_URL = os.environ.get("BILIAUTO_SERVER", "https://YOUR_SERVER_HOST:8788")

# 【必改】配对密钥
# 取服务器上 ~/.config/biliauto/pairing.key 的完整内容
# 查看： cat ~/.config/biliauto/pairing.key
PAIRING_KEY = os.environ.get("BILIAUTO_KEY", "YOUR_PAIRING_KEY")

# 同步到哪个应用下（空字符串 = 全局，所有应用都能看到）
# 例： com.tencent.mobileqq
SYNC_APP = os.environ.get("BILIAUTO_APP", "")

ROOT = Path(__file__).parent
LOCK = threading.Lock()


# ============ ADB ============
def _adb_cmd(*args: str) -> list[str]:
    cmd = [ADB]
    if SERIAL:
        cmd += ["-s", SERIAL]
    cmd += list(args)
    return cmd


def adb(*args: str, timeout: int = 20) -> tuple[int, str]:
    with LOCK:
        try:
            r = subprocess.run(_adb_cmd(*args), capture_output=True,
                               text=True, timeout=timeout)
            return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
        except subprocess.TimeoutExpired:
            return 1, "adb 超时"
        except FileNotFoundError:
            return 1, f"找不到 adb：{ADB}\n请安装 platform-tools 或设置 ADB_PATH 环境变量"
        except Exception as e:  # noqa: BLE001
            return 1, f"{type(e).__name__}: {e}"


def pick_device() -> str | None:
    """自动选一台在线设备。"""
    code, out = adb("devices")
    if code != 0:
        return None
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return None


def screenshot_bytes() -> bytes | None:
    """直接取 PNG 字节，不落盘（比先存再 pull 快一倍）。"""
    with LOCK:
        try:
            r = subprocess.run(_adb_cmd("exec-out", "screencap", "-p"),
                               capture_output=True, timeout=25)
            if r.returncode == 0 and r.stdout[:4] == b"\x89PNG":
                return r.stdout
        except Exception:  # noqa: BLE001
            pass
    return None


def tap(x: int, y: int) -> tuple[bool, str]:
    code, out = adb("shell", "input", "tap", str(int(x)), str(int(y)))
    return code == 0, out


def current_density() -> int | None:
    import re
    code, out = adb("shell", "wm", "density")
    if code != 0:
        return None
    m = re.search(r"Override density:\s*(\d+)", out)
    if m:
        return int(m.group(1))
    m = re.search(r"Physical density:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def set_dpi(mode: str) -> tuple[bool, int | None]:
    if mode == "reset":
        adb("shell", "wm", "density", "reset")
        return True, current_density()
    cur = current_density() or 320
    if mode == "up":
        new = min(640, cur + 20)
    elif mode == "down":
        new = max(80, cur - 20)
    elif mode.isdigit():
        new = max(80, min(640, int(mode)))
    else:
        return False, cur
    adb("shell", "wm", "density", str(new))
    return True, current_density()


# ============ HTTPS 支持 ============
# 服务器常用自签证书。这里装一个宽松的 SSL 上下文，
# 只跳过"证书是否是已知 CA 签发"这一项，其他校验（主机名等）照常。
_SSL_CTX = None


def ssl_ctx():
    """返回一个接受自签证书的 SSLContext。"""
    global _SSL_CTX
    if _SSL_CTX is not None:
        return _SSL_CTX
    import ssl
    ctx = ssl.create_default_context()
    # 不验证证书链（自签证书没有可信 CA）
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    _SSL_CTX = ctx
    return ctx


def urlopen(req, timeout: int = 15):
    """统一入口：HTTPS 走宽松上下文，HTTP 直连。"""
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if url.lower().startswith("https://"):
        return urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx())
    return urllib.request.urlopen(req, timeout=timeout)


# ============ 服务器同步 ============
def _sign(method: str, path: str, body: str) -> str:
    """HMAC-SHA256(key, METHOD\\nPATH\\nBODY)，与 biliauto 服务端一致。"""
    msg = (method.upper() + "\n" + path + "\n" + body).encode("utf-8")
    return hmac.new(PAIRING_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def sync_to_server(points: list[dict]) -> tuple[bool, str]:
    """把点位推到服务器。返回 (成功, 说明)。"""
    if not PAIRING_KEY:
        return False, "没有配置配对密钥（BILIAUTO_KEY），跳过同步"

    path = "/api/watch/points"
    payload = {
        "global": points if not SYNC_APP else [],
        "apps": {SYNC_APP: points} if SYNC_APP else {},
    }
    body = json.dumps(payload, ensure_ascii=False)
    sig = _sign("POST", path, body)

    url = SERVER_URL.rstrip("/") + path
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), method="POST",
        headers={"X-Bili-Sign": sig, "Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read() or b"{}")
            if data.get("ok"):
                return True, f"已同步 {len(points)} 个点位到服务器"
            return False, f"服务器返回失败：{data.get('error', '未知')}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "配对密钥不正确（401）"
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"连不上服务器：{e.reason}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def fetch_from_server() -> tuple[bool, list | str]:
    """从服务器拉当前点位，用于首次打开时展示。"""
    if not PAIRING_KEY:
        return False, "没有配置配对密钥"
    path = "/api/watch/points"
    sig = _sign("GET", path, "")
    url = SERVER_URL.rstrip("/") + path
    req = urllib.request.Request(url, headers={"X-Bili-Sign": sig})
    try:
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read() or b"{}")
            pts = list(data.get("global") or [])
            if SYNC_APP:
                pts += list((data.get("apps") or {}).get(SYNC_APP) or [])
            return True, pts
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# ============ HTTP 服务 ============
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        p = urlparse(self.path).path

        if p in ("/", "/tap.html"):
            self._file(ROOT / "tap.html", "text/html; charset=utf-8")
            return

        if p.startswith("/watch_now.png"):
            data = screenshot_bytes()
            if not data:
                self.send_error(503, "screenshot failed")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(data)
            return

        if p == "/points":
            f = ROOT / "points.json"
            data = []
            if f.exists():
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    data = []
            self._json(200, {"ok": True, "points": data})
            return

        if p == "/server_points":
            ok, pts = fetch_from_server()
            if ok:
                self._json(200, {"ok": True, "points": pts})
            else:
                self._json(200, {"ok": False, "error": pts})
            return

        if p == "/devices":
            code, out = adb("devices")
            self._json(200, {"ok": code == 0, "out": out})
            return

        if p == "/dpi":
            self._json(200, {"ok": True, "density": current_density()})
            return

        if p == "/config":
            self._json(200, {
                "ok": True,
                "server": SERVER_URL,
                "has_key": bool(PAIRING_KEY),
                "sync_app": SYNC_APP,
                "device": SERIAL or pick_device() or "",
            })
            return

        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self._json(400, {"ok": False, "error": "JSON 解析失败"})
            return

        if p == "/tap":
            x, y = int(body.get("x", 0)), int(body.get("y", 0))
            ok, out = tap(x, y)
            self._json(200, {"ok": ok, "out": out})
            return

        if p == "/tap_all":
            pts = body.get("points") or []
            done, errs = 0, []
            for pt in pts:
                ok, out = tap(int(pt.get("x", 0)), int(pt.get("y", 0)))
                if ok:
                    done += 1
                else:
                    errs.append(out)
                time.sleep(1.0)
            self._json(200, {"ok": done > 0, "done": done, "errors": errs[:3]})
            return

        if p == "/save_points":
            pts = body.get("points") or []
            # 1) 存本地
            (ROOT / "points.json").write_text(
                json.dumps(pts, ensure_ascii=False, indent=2), encoding="utf-8")
            # 2) 同步到服务器
            synced, sync_msg = sync_to_server(pts)
            self._json(200, {
                "ok": True,
                "count": len(pts),
                "synced": synced,
                "sync_msg": sync_msg,
            })
            return

        if p == "/dpi":
            mode = str(body.get("mode") or "")
            ok, cur = set_dpi(mode)
            self._json(200, {"ok": ok, "density": cur})
            return

        self.send_error(404)


def main() -> int:
    global SERIAL
    print("=" * 56)
    print("  手表点选工具")
    print("=" * 56)

    code, out = adb("devices")
    if code != 0:
        print("[!] adb 不可用：", out)
        return 1
    print(out)

    if not SERIAL:
        SERIAL = pick_device() or ""
    if SERIAL:
        print(f"[+] 使用设备：{SERIAL}")
    else:
        print("[!] 没有检测到设备，请连接手表并开启 USB 调试")

    print(f"[+] 服务器：{SERVER_URL}")
    print(f"[+] 配对密钥：{'已配置' if PAIRING_KEY else '未配置（不会同步）'}")
    if SYNC_APP:
        print(f"[+] 同步到应用：{SYNC_APP}")
    else:
        print("[+] 同步到：全局（所有应用可见）")

    print()
    print("  打开浏览器访问： http://127.0.0.1:8765")
    print("  按 Ctrl+C 停止")
    print("=" * 56)

    srv = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
