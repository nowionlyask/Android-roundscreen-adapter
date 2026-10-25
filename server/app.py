#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watch Control 中转服务。

提供点选工具和手表 App 需要的全部 HTTP 接口：

    GET  /api/watch/status          手表状态（连接、DPI、前台应用、点位）
    GET  /api/watch/points          读取点位配置
    POST /api/watch/points          保存点位配置
    POST /api/watch/tap             注入点击 {"x":100,"y":200}
    POST /api/watch/dpi             改 DPI {"dpi":120} 或 {"dpi":"reset"}
    POST /api/watch/key             注入按键 {"code":4}
    POST /api/watch/launch          启动应用 {"package":"..."}
    GET  /api/watch/shot            截图 PNG
    GET  /api/watch/ime             输入法列表
    POST /api/watch/ime             切换输入法 {"id":"..."}

鉴权：所有 /api/ 请求需要 HMAC 签名头：

    X-Bili-Sign: HMAC-SHA256(key, METHOD + "\\n" + PATH + "\\n" + BODY) 的十六进制

其中 key 是 pairing.key 里的 64 个 ASCII 字符本身，PATH 不含 query string。

用法：

    export WATCH_ADDR="192.168.1.50:5555"
    export PAIRING_KEY="$(cat ~/.config/watch-control/pairing.key)"
    python app.py

默认监听 127.0.0.1:8787。用 --host 0.0.0.0 可以对外暴露。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ============================================================
# 配置
# ============================================================

# 手表的 ADB 地址。也可用环境变量覆盖。
WATCH_ADDR = os.environ.get("WATCH_ADDR", "")

# 电脑上 adb 的路径。留空用系统 PATH 里的。
ADB_PATH = os.environ.get("ADB_PATH", "adb")

# 配对密钥。留空则从文件读。
PAIRING_KEY = os.environ.get("PAIRING_KEY", "")

# 配置目录
CONFIG_HOME = Path(os.environ.get(
    "WC_HOME", str(Path.home() / ".config" / "watch-control")))

POINTS_FILE = CONFIG_HOME / "points.json"
KEY_FILE = CONFIG_HOME / "pairing.key"

# 默认 DPI（方便恢复）
DEFAULT_DPI = int(os.environ.get("WC_DEFAULT_DPI", "120"))

log = logging.getLogger("watch-control")

_lock = threading.Lock()
_last_learned = ""


# ============================================================
# ADB
# ============================================================

def _adb_cmd(*args: str) -> list[str]:
    cmd = [ADB_PATH]
    if WATCH_ADDR:
        cmd += ["-s", WATCH_ADDR]
    cmd += list(args)
    return cmd


def adb(*args: str, timeout: int = 15) -> tuple[int, str]:
    """执行 adb 命令，返回 (返回码, 输出)。"""
    with _lock:
        try:
            r = subprocess.run(_adb_cmd(*args), capture_output=True,
                               text=True, timeout=timeout)
            out = (r.stdout or "") + (r.stderr or "")
            return r.returncode, out.strip()
        except subprocess.TimeoutExpired:
            return 1, "adb 超时"
        except FileNotFoundError:
            return 1, "找不到 adb：{}".format(ADB_PATH)
        except Exception as e:  # noqa: BLE001
            return 1, "{}: {}".format(type(e).__name__, e)


def ensure_connected() -> bool:
    """确认 adb 能操作到手表。"""
    if not WATCH_ADDR:
        return False
    code, out = adb("get-state", timeout=4)
    if code == 0 and "device" in out:
        return True
    # 尝试重连
    try:
        subprocess.run([ADB_PATH, "connect", WATCH_ADDR],
                       capture_output=True, timeout=6)
    except Exception:  # noqa: BLE001
        pass
    code, out = adb("get-state", timeout=4)
    return code == 0 and "device" in out


def learn_watch_ip(ip: str) -> None:
    """手表访问服务器时，用来源 IP 自动校正 ADB 地址。

    蜂窝网络的 IPv6 是动态分配的，会变。手表每次打开 App 都会请求，
    这时候的来源地址就是它当前的地址，比人工维护可靠。
    """
    global WATCH_ADDR, _last_learned

    if not ip or ip.startswith(("127.", "::1", "::ffff:127.", "fe80", "fd", "fc")):
        return

    new_addr = "[{}]:5555".format(ip) if ":" in ip else "{}:5555".format(ip)
    if new_addr == WATCH_ADDR or new_addr == _last_learned:
        return

    old = WATCH_ADDR
    WATCH_ADDR = new_addr
    _last_learned = new_addr
    log.info("手表地址更新: %s -> %s", old or "(空)", new_addr)

    def _reconnect() -> None:
        try:
            if old:
                subprocess.run([ADB_PATH, "disconnect", old],
                               capture_output=True, timeout=5)
            subprocess.run([ADB_PATH, "connect", new_addr],
                           capture_output=True, timeout=8)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_reconnect, daemon=True).start()


# ============================================================
# 手表操作
# ============================================================

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


def set_density(value) -> tuple[bool, int | None]:
    if value is None or value == "reset":
        adb("shell", "wm", "density", "reset")
    else:
        adb("shell", "wm", "density", str(int(value)))
    return True, current_density()


def tap(x: int, y: int) -> tuple[bool, str]:
    """注入点击。自己判断成败，避免"接口 200 但没点下去"。"""
    if not ensure_connected():
        return False, "手表未连接（{}）".format(WATCH_ADDR or "未配置")
    code, out = adb("shell", "input", "tap", str(int(x)), str(int(y)))
    if "not found" in out.lower() or "error" in out.lower():
        return False, out
    return code == 0, out


def tap_key(code: int) -> tuple[bool, str]:
    if not ensure_connected():
        return False, "手表未连接"
    c, out = adb("shell", "input", "keyevent", str(int(code)))
    return c == 0, out


def app_info() -> dict:
    import re
    code, out = adb("shell", "dumpsys activity activities")
    m = re.search(r"mResumedActivity.*?u0\s+([\w.]+)/([\w.$]+)", out)
    if m:
        return {"package": m.group(1), "activity": m.group(2)}
    return {}


def launch_app(package: str) -> tuple[bool, str]:
    if not ensure_connected():
        return False, "手表未连接"
    code, out = adb("shell", "monkey", "-p", package,
                    "-c", "android.intent.category.LAUNCHER", "1")
    return code == 0, out


def screenshot_bytes() -> bytes | None:
    if not ensure_connected():
        return None
    try:
        r = subprocess.run(_adb_cmd("exec-out", "screencap", "-p"),
                           capture_output=True, timeout=25)
        if r.returncode == 0 and r.stdout[:4] == b"\x89PNG":
            return r.stdout
    except Exception:  # noqa: BLE001
        pass
    return None


def ime_status() -> dict:
    cur = adb("shell", "settings get secure default_input_method")[1].strip()
    enabled = adb("shell", "settings get secure enabled_input_methods")[1].strip()
    raw = adb("ime list -a -s")[1]
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        pkg = line.split("/")[0]
        items.append({
            "id": line,
            "package": pkg,
            "label": pkg,
            "active": line == cur,
        })
    return {"current": cur, "enabled": enabled.split(":") if enabled else [],
            "available": items}


def set_ime(ime_id: str) -> tuple[bool, str]:
    st = ime_status()
    enabled = st["enabled"]
    if ime_id not in enabled:
        enabled.append(ime_id)
        adb("shell", "settings put secure enabled_input_methods "
                     + ":".join(enabled))
    adb("shell", "ime enable", ime_id)
    c, out = adb("shell", "ime", "set", ime_id)
    return c == 0, out or "ok"


# ============================================================
# 点位配置
# ============================================================

def load_points() -> dict:
    """结构：{"global": [...], "apps": {"包名": [...]}}"""
    if not POINTS_FILE.exists():
        return {"global": [], "apps": {}}
    try:
        d = json.loads(POINTS_FILE.read_text(encoding="utf-8"))
        if isinstance(d, list):
            return {"global": d, "apps": {}}
        d.setdefault("global", [])
        d.setdefault("apps", {})
        return d
    except Exception:  # noqa: BLE001
        return {"global": [], "apps": {}}


def save_points(data: dict) -> bool:
    try:
        CONFIG_HOME.mkdir(parents=True, exist_ok=True)
        POINTS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        log.exception("保存点位失败")
        return False


def status() -> dict:
    """完整状态。点位不依赖 ADB，连不上也要能返回。"""
    out = {
        "ok": True,
        "connected": False,
        "density": None,
        "default_dpi": DEFAULT_DPI,
        "front": {},
        "points": load_points(),
        "watch_addr": WATCH_ADDR,
    }
    try:
        if ensure_connected():
            out["connected"] = True
            out["density"] = current_density()
            out["front"] = app_info() or {}
    except Exception:  # noqa: BLE001
        pass
    return out


# ============================================================
# HTTP
# ============================================================

def _sign(method: str, path: str, body: str) -> str:
    msg = (method.upper() + "\n" + path + "\n" + body).encode("utf-8")
    return hmac.new(PAIRING_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()


class Handler(BaseHTTPRequestHandler):
    server_version = "WatchControl/1.0"

    def log_message(self, fmt, *args):  # noqa: A003
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, body: bytes, path: str) -> bool:
        if not PAIRING_KEY:
            return True      # 没配密钥就不鉴权（仅本机使用建议）
        sig = self.headers.get("X-Bili-Sign", "")
        try:
            expect = _sign(self.command, path, body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return False
        return hmac.compare_digest(sig.lower(), expect.lower())

    def _learn(self) -> None:
        try:
            ip = self.client_address[0] if self.client_address else ""
            learn_watch_ip(ip)
        except Exception:  # noqa: BLE001
            pass

    def do_GET(self) -> None:  # noqa: N802
        p = urlparse(self.path).path
        self._learn()

        if not self._authorized(b"", p):
            return self._json(401, {"ok": False, "error": "签名无效"})

        if p == "/api/watch/status":
            return self._json(200, status())

        if p == "/api/watch/points":
            return self._json(200, dict(ok=True, **load_points()))

        if p == "/api/watch/shot":
            data = screenshot_bytes()
            if not data:
                return self._json(503, {"ok": False, "error": "截图失败"})
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return None

        if p == "/api/watch/ime":
            return self._json(200, dict(ok=True, **ime_status()))

        return self._json(404, {"ok": False, "error": "no_route"})

    def do_POST(self) -> None:  # noqa: N802
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        self._learn()

        if not self._authorized(raw, p):
            return self._json(401, {"ok": False, "error": "签名无效"})

        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._json(400, {"ok": False, "error": "JSON 解析失败"})

        if p == "/api/watch/tap":
            ok, out = tap(int(body.get("x", 0)), int(body.get("y", 0)))
            return self._json(200, {"ok": ok, "out": out})

        if p == "/api/watch/key":
            ok, out = tap_key(int(body.get("code", 4)))
            return self._json(200, {"ok": ok, "out": out})

        if p == "/api/watch/launch":
            ok, out = launch_app(str(body.get("package", "")))
            return self._json(200, {"ok": ok, "out": out})

        if p == "/api/watch/dpi":
            ok, cur = set_density(body.get("dpi"))
            return self._json(200, {"ok": ok, "density": cur})

        if p == "/api/watch/points":
            ok = save_points({
                "global": body.get("global") or [],
                "apps": body.get("apps") or {},
            })
            return self._json(200, {"ok": ok})

        if p == "/api/watch/ime":
            ime_id = str(body.get("id") or "")
            if not ime_id:
                return self._json(400, {"ok": False, "error": "缺少 id"})
            ok, out = set_ime(ime_id)
            return self._json(200, {"ok": ok, "out": out,
                                    "current": ime_status()["current"]})

        return self._json(404, {"ok": False, "error": "no_route"})


# ============================================================
# 启动
# ============================================================

def load_key() -> str:
    """读取配对密钥。优先环境变量，其次文件。"""
    if PAIRING_KEY:
        return PAIRING_KEY
    if KEY_FILE.exists():
        try:
            return KEY_FILE.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            pass
    return ""


def ensure_self_signed() -> tuple[str, str]:
    """生成（或复用）自签名证书，返回 (cert, key) 路径。

    证书放在配置目录下，只在不存在时生成。
    用 openssl 命令行生成，避免引入 Python 的加密库依赖。
    """
    cert = CONFIG_HOME / "server.crt"
    key = CONFIG_HOME / "server.key"

    if cert.exists() and key.exists():
        log.info("复用已有自签名证书: %s", cert)
        return str(cert), str(key)

    import shutil
    import subprocess as sp

    openssl = shutil.which("openssl")
    if not openssl:
        print("[!] 找不到 openssl，无法生成自签名证书")
        print("    Windows 可以安装 Git for Windows，或用 WSL")
        print("    也可以手动指定 --tls-cert / --tls-key")
        raise SystemExit(1)

    CONFIG_HOME.mkdir(parents=True, exist_ok=True)
    print("[*] 生成自签名证书（有效期 10 年）...")

    cmd = [
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert),
        "-days", "3650",
        "-subj", "/CN=watch-control",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ]
    r = sp.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # 老版本 openssl 没有 -addext
        cmd = cmd[:-2]
        r = sp.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("[!] 生成失败:", r.stderr[:300])
            raise SystemExit(1)

    try:
        os.chmod(key, 0o600)
    except Exception:  # noqa: BLE001
        pass

    print("[+] 证书: {}".format(cert))
    print("[+] 私钥: {}（请勿外传）".format(key))
    print("[!] 把证书复制到 APK 资源目录以下使其被信任:")
    print("    cp {} android/res/raw/pi_cert.pem".format(cert))
    return str(cert), str(key)


def main() -> int:
    global PAIRING_KEY, WATCH_ADDR

    ap = argparse.ArgumentParser(description="Watch Control 中转服务")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址")
    ap.add_argument("--port", type=int, default=0,
                    help="监听端口（默认 http 8787 / https 8788）")
    ap.add_argument("--tls-cert", default="", help="TLS 证书路径（启用 HTTPS）")
    ap.add_argument("--tls-key", default="", help="TLS 私钥路径")
    ap.add_argument("--self-signed", action="store_true",
                    help="自动生成自签名证书并启用 HTTPS")
    ap.add_argument("--verbose", action="store_true", help="输出详细日志")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")

    PAIRING_KEY = load_key()
    CONFIG_HOME.mkdir(parents=True, exist_ok=True)

    # ---- TLS 准备 ----
    cert_path = args.tls_cert
    key_path = args.tls_key

    if args.self_signed:
        cert_path, key_path = ensure_self_signed()

    use_tls = bool(cert_path and key_path)
    port = args.port or (8788 if use_tls else 8787)

    print("=" * 56)
    print("  Watch Control 中转服务")
    print("=" * 56)
    print("  手表地址 : {}".format(WATCH_ADDR or "(未配置，将由访问自动学习)"))
    print("  adb      : {}".format(ADB_PATH))
    print("  配对密钥 : {}".format("已配置" if PAIRING_KEY else "未配置（不鉴权）"))
    print("  配置目录 : {}".format(CONFIG_HOME))
    print("  点位数   : {}".format(len(load_points().get("global") or [])))
    print("  协议     : {}".format("HTTPS" if use_tls else "HTTP"))
    print()
    print("  监听 {}://{}:{}".format(
        "https" if use_tls else "http", args.host, port))
    print("  按 Ctrl+C 停止")
    print("=" * 56)

    srv = ThreadingHTTPServer((args.host, port), Handler)

    if use_tls:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
