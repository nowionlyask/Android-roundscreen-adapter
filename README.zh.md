# Watch Control

> [English](README.md) | **中文**

> ## ⚠️ 技术示例，风险自负
>
> **这是一个技术演示项目，仅供学习研究，不是开箱即用的产品。**
>
> 它涉及 ADB 调试、修改屏幕密度、注入触摸事件、安装第三方应用，
> **可能损坏你的设备、导致数据丢失、使保修失效、或让账号被封禁。**
>
> **一切后果由你自行承担，作者不承担任何责任。**
>
> 不要在你不拥有的设备上使用。不要用它违反任何法律或平台服务条款。
>
> [MIT](#许可证) 许可 —— 随便用，出事自己担。

在电脑浏览器里点选坐标 → 同步到服务器 → 在安卓手表的悬浮窗上一键点按。

演示的技术点：安卓悬浮窗、ADB 调试接口、WebView ↔ 原生代码桥接、
HMAC 请求签名、自签证书在 Android 中的信任配置。

---

## 结构

```
┌─────────────────┐    HTTPS + HMAC     ┌──────────────┐
│  电脑浏览器      │ ──────────────────> │    服务器     │
│  tap-tool 网页   │   保存时自动同步     │  (Pi / NAS)  │
└─────────────────┘                     └──────┬───────┘
        │                                      │
        │ USB / adb                            │ ADB over WiFi
        ▼                                      ▼
┌─────────────────┐                     ┌──────────────┐
│   手表（截屏）   │ <─────────────────> │   手表悬浮窗  │
└─────────────────┘                     └──────────────┘
```

| 目录 | 内容 | 跑在哪 |
|---|---|---|
| `android/` | 手表 App —— 悬浮按钮、转发点击 | 手表 |
| `tap-tool/` | 点选工具 —— 截图、记录坐标 | 电脑 |
| `server/` | 中转层 —— 存点位、控制 ADB | 树莓派/NAS |

## 配置

所有属于**你自己**的值都是占位符。**不改就什么都跑不起来。**

### 占位符总览

| 占位符 | 位置 | 怎么获取 |
|---|---|---|
| `YOUR_SERVER_IPV6` | `android/MainActivity.java`<br>`android/res/xml/network_security_config.xml` | 服务器上 `ip -6 addr show scope global` |
| `YOUR_WATCH_TOKEN` | `android/MainActivity.java` | `python3 -c "import secrets; print(secrets.token_hex(12))"` |
| `YOUR_PAIRING_KEY` | `android/MainActivity.java` | `cat ~/.config/biliauto/pairing.key` |
| `YOUR_SERVER_HOST` | `tap-tool/env.sh` | 同一个 IP，不要方括号 |
| `YOUR_DEVICE_SERIAL` | 环境变量 `ADB_SERIAL` | `adb devices`（可选） |
| `WATCH_IPV6` | `server/watchctl.py` | `adb shell ip -6 addr show` —— **手表**的 IP |

### 1. 生成配对密钥

```bash
mkdir -p ~/.config/biliauto
python3 -c "import secrets; print(secrets.token_hex(32))" \
  > ~/.config/biliauto/pairing.key
chmod 600 ~/.config/biliauto/pairing.key
```

### 2. 手表开启 ADB

```bash
adb devices                  # 状态要是 device，不能是 unauthorized
adb tcpip 5555               # 开启网络监听
adb connect <手表IP>:5555     # 测试连接
```

第一次连接手表会弹授权框，点**允许**。

### 3. 打包证书

如果服务器用的是自签 HTTPS 证书：

```bash
cp server.crt android/res/raw/pi_cert.pem
```

文件名**必须**是 `pi_cert.pem`，`network_security_config.xml` 里写死了这个名。
**换证书后必须重新打包 APK。**

用公共 CA（Let's Encrypt 等）的话跳过这步，系统信任库本身就认。

### 4. 编译手表 App

```bash
cd android
# 编辑 MainActivity.java，设置 BASE_URL、TOKEN、KEY
python compile.py
adb install -r watch-control.apk
```

### 5. 运行点选工具

```bash
cd tap-tool
export ADB_PATH=/path/to/adb
export ADB_SERIAL=你的手表序列号
export BILIAUTO_SERVER=https://你的服务器:8788
export BILIAUTO_KEY=$(cat ~/.config/biliauto/pairing.key)
python serve.py
```

浏览器打开 <http://127.0.0.1:8765>。

### 6. 添加点位

1. 左边是手表实时画面（每秒刷新）
2. 在图上点你要按的位置
3. 起个名字，点**记录这个点**
4. 加完点**保存点位**

保存会写入本地 `points.json` 并 POST 到 `/api/watch/points`。
手表上刷新悬浮窗就能看到新按钮。

检查配置有没有漏改：

```bash
python check_config.py     # 列出所有未替换的占位符
```

## 点选工具功能

| 功能 | 说明 |
|---|---|
| 实时截图 | 每秒刷新，延迟约 350ms |
| 点击预览 | 点已记录的点可以直接试 |
| 快捷按钮 | 每个点位一个按钮 |
| DPI 控制 | 320 / 120 / 100 / 恢复 |
| 自动同步 | 保存时推送到服务器 |
| 按应用区分 | 设置 `BILIAUTO_APP` 后只在指定应用显示 |

## 手表 App 交互

- 小浮球（≡）默认在**屏幕正中**，可自由拖动，不吸附边缘
- **点一下**展开环形按钮
- **按钮沿圆周等距排布**，数量多了自动往里收；一圈最多 10 个，超出排到内圈
- **点面板外区域**收起，浮球回到原来的位置
- **收起时窗口只有 48dp**，不拦截其他应用的触摸

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `ADB_PATH` | `adb` | adb 可执行文件路径 |
| `ADB_SERIAL` | 自动 | 目标设备序列号 |
| `BILIAUTO_SERVER` | `https://YOUR_SERVER_HOST:8788` | 服务器地址 |
| `BILIAUTO_KEY` | 空 | 配对密钥，空则不启用同步 |
| `BILIAUTO_APP` | 空 | 点位归属的应用包名 |

## 安全

**两条链路都走 HTTPS。** 点选工具内置了接受自签证书的 SSL 上下文
（`ssl.CERT_NONE`），所以没有公共 CA 也能连自己的服务器。

每个请求带 HMAC-SHA256 签名，放在 `X-Bili-Sign` 头里：

```
HMAC-SHA256(pairing_key, METHOD + "\n" + PATH + "\n" + BODY)  的十六进制
```

- `pairing_key` 是 `pairing.key` 里的 **64 个 ASCII 字符本身**，
  不是 hex 解码后的 32 字节
- `PATH` 不含 query string
- 密钥文件权限要 `chmod 600`

点选工具**只监听 127.0.0.1**。悬浮窗权限需要手动授予。

## 已知限制

- 老 WebView（比如 83）在非安全上下文下没有 `crypto.subtle`。
  签名优先走 Java 桥，JS 侧有纯 JS 的 SHA-256 兜底
- 改 DPI 会让屏幕逻辑尺寸变化，浮球位置会被重新夹紧（不吸附）
- 手表熄屏后 App 进后台，页面停止刷新

## 常见问题

**手表 App 一直显示"连接中"**
→ 证书没打进去。检查 `android/res/raw/pi_cert.pem` 存在且重新编译过 APK。
自签证书在 TLS 握手阶段就会失败，`onReceivedSslError` 根本不会触发。

**点按钮没反应**
→ `server/watchctl.py` 里的 `WATCH_ADDR` 填错了，或手表没开网络调试。

**状态栏显示红点**
→ 密钥不对或服务器连不上：

```bash
curl -k https://你的服务器:8788/api/watch/points
# 401 = 通了但密钥错
# 超时 = 网络不通
```

## 免责

见顶部警告。简而言之：

- **技术示例，不是产品。** 不提供支持、不做保证、不负责维护。
- **一切风险由你承担。** 设备损坏、数据丢失、保修失效、账号封禁、
  法律责任 —— 全是你的。
- **只在你自己拥有的设备上用**，用于合法目的，遵守适用法律和平台条款。
- **与任何厂商无关。** 提及的商标归各自权利人所有。
- **本文仅供参考。** 不构成对作者的义务，也不是法律建议。

## 许可证

[MIT](LICENSE) —— 想怎么用就怎么用，包括商业用途，风险自负。
MIT 的免责条款完整适用。

```
Copyright (c) 2026 watch-control contributors
```
