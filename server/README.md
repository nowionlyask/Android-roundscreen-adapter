# 服务器端

服务器负责三件事：

1. 保存点位配置（`watch_points.json`）
2. 通过 ADB 控制手表（改 DPI、注入点击、截图）
3. 给手表 App 提供 HTTP 接口

推荐用树莓派这类常开设备。

## 依赖

```bash
# ADB
sudo apt install -y adb

# Python 3.9+
python3 -m venv ~/.venvs/watchctl
~/.venvs/watchctl/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    requests
```

## 1. 让服务器能控制手表

手表和服务器需要在同一网络（或者服务器能访问手表的 IP）。

### 方式 A：USB 直连（最简单）

```bash
adb devices
# 应该看到你的手表
```

### 方式 B：ADB over WiFi / IPv6

手表连 WiFi 后，开启网络调试：

```bash
adb tcpip 5555
adb connect <手表IP>:5555
```

如果手表用的是**蜂窝网络的 IPv6**，直接填 IPv6 地址：

```bash
adb connect '[2408:xxxx:xxxx:xxxx::1]:5555'
```

第一次连接时手机会弹授权框，点「允许」，建议勾上「一律允许」。

## 2. 配对密钥

手表 App 和点选工具都用这个密钥给请求签名。

```bash
mkdir -p ~/.config/biliauto
# 生成 32 字节的随机密钥（64 个十六进制字符）
python3 -c "import secrets; print(secrets.token_hex(32))" > ~/.config/biliauto/pairing.key
chmod 600 ~/.config/biliauto/pairing.key
cat ~/.config/biliauto/pairing.key
```

## 3. 点位配置

`~/.config/biliauto/watch_points.json`：

```json
{
  "global": [
    {"name": "动态", "x": 409, "y": 446},
    {"name": "消息", "x": 61, "y": 438}
  ],
  "apps": {
    "com.tencent.mobileqq": [
      {"name": "发送", "x": 400, "y": 420}
    ]
  }
}
```

- `global` — 所有应用都显示的按钮
- `apps` — 按包名分组的按钮，只在对应应用前台时显示

通常不用手写，用点选工具保存时会自动生成。

## 4. 接口

所有接口需要签名头：

```
X-Bili-Sign: HMAC-SHA256(key, METHOD + "\n" + PATH + "\n" + BODY) 的十六进制
```

注意 `PATH` **不含 query string**，`key` 是 pairing.key 里的 64 个 ASCII 字符（不是 hex 解码后的字节）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/watch/status` | 手表状态（连接、DPI、前台应用、点位） |
| GET | `/api/watch/points` | 读取点位配置 |
| POST | `/api/watch/points` | 保存点位配置 |
| POST | `/api/watch/tap` | 注入点击 `{"x":100,"y":200}` |
| POST | `/api/watch/dpi` | 改 DPI `{"dpi":120}` 或 `{"dpi":"reset"}` |
| GET | `/api/watch/shot` | 截图 PNG |
| GET | `/api/watch/ime` | 输入法列表 |
| POST | `/api/watch/ime` | 切换输入法 `{"id":"..."}` |
| GET | `/api/watch/rollback` | 读取原始状态备份 |

### 签名示例（Python）

```python
import hashlib, hmac, json, urllib.request

KEY = open("~/.config/biliauto/pairing.key").read().strip()
BASE = "http://127.0.0.1:8787"

def call(method, path, payload=None):
    body = json.dumps(payload).encode() if payload else b""
    msg = (method + "\n" + path + "\n").encode() + body
    sig = hmac.new(KEY.encode(), msg, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        BASE + path, data=(body or None), method=method,
        headers={"X-Bili-Sign": sig, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# 读状态
print(call("GET", "/api/watch/status"))

# 点一下屏幕中心
print(call("POST", "/api/watch/tap", {"x": 233, "y": 233}))

# 设 DPI
print(call("POST", "/api/watch/dpi", {"dpi": 120}))
```

## 5. 开机自启（可选）

`/etc/systemd/system/watchctl.service`：

```ini
[Unit]
Description=Watch control server
After=network-online.target

[Service]
Type=simple
User=pi
Environment=BILIAUTO_KEY_FILE=/home/pi/.config/biliauto/pairing.key
ExecStart=/home/pi/.venvs/watchctl/bin/python -m http.server 8787
Restart=always

[Install]
WantedBy=multi-user.target
```

## 常见问题

**Q: `adb connect` 后显示 `unauthorized`**
手表上要有授权弹窗，点允许。如果没弹，拔插一次 USB 或重启手表。

**Q: 改 DPI 后悬浮球跑角落 / 按不着**
App 已经处理了：DPI 变化后会重新夹紧坐标，且不吸附边缘。如果仍有问题，
把浮球拖回去，然后检查 `onConfigurationChanged` 是否被调用。

**Q: 手表页面一直显示「连接中」**
大概率是**证书问题**。服务器的自签名证书必须在 APK 的
`network_security_config.xml` 里显式信任，否则 WebView 在握手阶段就失败，
连 `onReceivedSslError` 回调都不会触发。

**Q: 注入点击没反应**
确认 `adb shell input tap` 在命令行能工作。某些定制 ROM 会拦 shell 的注入权限。
