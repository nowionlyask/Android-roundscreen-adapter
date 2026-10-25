# Watch Control

> [English](README.md) | **中文**

## 项目简介

Watch Control 是一个技术演示项目，用于展示如何协同使用桌面浏览器、轻量中转服务和
Android 手表三端。用户可在手表截图上选取坐标，将坐标保存至服务器，随后通过手表上
的悬浮窗调用这些坐标。

本项目可作为若干常见穿戴设备开发技巧的参考实现，包括：Android 悬浮窗、ADB 调试接口、
WebView 与原生代码之间的双向通信、基于 HMAC 的请求签名，以及在 Android 应用中信任
自签名证书。

## 重要说明

本项目为学习与实验用途的演示项目，并非成品，亦不保证其正确性、稳定性或适用性。

项目演示的技术涉及系统级操作，包括启用 ADB、调整显示密度、注入输入事件以及安装第三方
应用。此类操作具有固有风险，在部分设备上可能导致数据丢失、保修失效或系统行为异常。
如需进行实验，建议在您本人拥有且可承担风险的设备上进行。

对第三方平台的自动化操作也可能与该平台的服务条款相冲突。使用前请阅读并遵守相关协议。

您需对使用本项目的方式负责。作者不承担因使用本项目而产生的任何后果。

## 系统结构

系统由三个协同工作的部分组成。

```
┌─────────────────┐    HTTPS + HMAC     ┌──────────────┐
│  电脑浏览器      │ ──────────────────> │    服务器     │
│  tap-tool 网页   │    保存时自动同步    │  (Pi / NAS)  │
└─────────────────┘                     └──────┬───────┘
        │                                      │
        │ USB / adb                            │ ADB over WiFi
        ▼                                      ▼
┌─────────────────┐                     ┌──────────────┐
│   手表（截屏）   │ <─────────────────> │   手表悬浮窗  │
└─────────────────┘                     └──────────────┘
```

| 目录 | 用途 | 运行位置 |
|---|---|---|
| `android/` | 手表应用，负责渲染悬浮层并转发点击事件 | 手表 |
| `tap-tool/` | 桌面工具，负责截取画面并记录坐标 | 电脑 |
| `server/` | 中转服务，负责存储配置并执行 ADB 命令 | 树莓派 / NAS |

## 开始使用

仓库中凡是依赖您自身环境的值均以占位符表示，需先行替换，系统方可正常运行。

### 占位符说明

| 占位符 | 位置 | 获取方式 |
|---|---|---|
| `YOUR_SERVER_IPV6` | `android/MainActivity.java`、`network_security_config.xml` | 在服务器上执行 `ip -6 addr show scope global` |
| `YOUR_WATCH_TOKEN` | `android/MainActivity.java` | 通过 `secrets.token_hex(12)` 生成 |
| `YOUR_PAIRING_KEY` | `android/MainActivity.java` | `~/.config/biliauto/pairing.key` 的内容 |
| `YOUR_SERVER_HOST` | `tap-tool/env.sh` | 与上述地址相同，无需方括号 |
| `YOUR_DEVICE_SERIAL` | 环境变量 `ADB_SERIAL` | 由 `adb devices` 列出（可选） |
| `WATCH_IPV6` | `server/watchctl.py` | 手表自身的地址，通过 `adb shell ip -6 addr show` 获取 |

执行 `python check_config.py` 可列出所有尚未替换的占位符。

### 准备服务器

首先需要生成配对密钥，该密钥用于校验手表应用与中转服务之间的请求。

```bash
mkdir -p ~/.config/biliauto
python3 -c "import secrets; print(secrets.token_hex(32))" \
  > ~/.config/biliauto/pairing.key
chmod 600 ~/.config/biliauto/pairing.key
```

### 准备手表

在手表的开发者选项中启用 ADB 调试，随后确认连接状态。首次连接时手表将显示授权提示。

```bash
adb devices                  # 应显示 device，而非 unauthorized
adb tcpip 5555               # 启用网络调试
adb connect <手表IP>:5555     # 验证连接
```

### 证书配置

若中转服务使用自签名证书，请将其放入应用资源目录：

```bash
cp server.crt android/res/raw/pi_cert.pem
```

文件名须保持为 `pi_cert.pem`，因为 `network_security_config.xml` 中引用的正是该名称。
证书重新生成后，需要重新编译 APK。

若使用公共机构签发的证书，则可跳过此步骤，系统默认会查询系统信任库。

### 编译手表应用

```bash
cd android
# 请先在 MainActivity.java 中设置 BASE_URL、TOKEN 与 KEY
python compile.py
adb install -r watch-control.apk
```

### 运行桌面工具

```bash
cd tap-tool
export ADB_PATH=/path/to/adb
export ADB_SERIAL=你的手表序列号
export BILIAUTO_SERVER=https://你的服务器:8788
export BILIAUTO_KEY=$(cat ~/.config/biliauto/pairing.key)
python serve.py
```

随后可通过 <http://127.0.0.1:8765> 访问界面。

### 记录坐标

界面左侧显示手表的实时画面，约每秒刷新一次。在画面上点击即可记录对应坐标，为其命名并
按下**记录这个点**即可加入列表。列表完成后，按下**保存点位**会将配置写入本地并同步至
中转服务。手表悬浮层刷新后即可反映更新。

## 功能说明

桌面工具提供手表画面的实时显示、可调的显示密度（320、120、100 或系统默认值）、对任
意已记录坐标的直接测试，以及与中转服务的自动同步。通过 `BILIAUTO_APP` 可将坐标限定
于特定应用包名。

手表应用呈现一个小型可拖动的把手，点击后展开为沿圆周均匀排布的按钮。随着坐标数量增加，
半径会相应调整，外圈最多容纳十个，多余的坐标排列于内圈。把手在收起状态下仅占用 48 dp，
不会干扰其他应用。

## 配置项

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ADB_PATH` | `adb` | adb 可执行文件路径 |
| `ADB_SERIAL` | 自动检测 | 目标设备序列号 |
| `BILIAUTO_SERVER` | `https://YOUR_SERVER_HOST:8788` | 中转服务地址 |
| `BILIAUTO_KEY` | 空 | 配对密钥，为空时不同步 |
| `BILIAUTO_APP` | 空 | 坐标所属的应用包名 |

## 安全说明

两条通信链路均使用 HTTPS。桌面工具内置了接受自签名证书的 SSL 上下文，因此在没有公共
机构证书的情况下，同样可以与私有中转服务通信。

每个请求均在 `X-Bili-Sign` 头中携带 HMAC-SHA256 签名。

```
HMAC-SHA256(配对密钥, METHOD + "\n" + PATH + "\n" + BODY)  的十六进制
```

配对密钥为 `pairing.key` 中存储的 64 个 ASCII 字符，而非按十六进制解析后的 32 字节。
路径部分不含查询字符串。密钥文件应仅允许其所有者读取。

桌面工具仅监听 `127.0.0.1`，手表端的悬浮窗权限需由用户手动授予。

## 已知限制

较旧的 WebView 实现（例如版本 83）在非安全上下文中不提供 `crypto.subtle`。因此签名
优先经由 Java 桥接完成，并以纯 JavaScript 的 SHA-256 实现作为后备。

调整显示密度会改变屏幕的逻辑尺寸，把手位置随后会被限制回可视范围，而非吸附至边缘。

当手表熄屏时，应用转入后台，页面将停止刷新。

## 问题排查

若手表应用始终停留在“连接中”，通常是 APK 中缺少证书。自签名证书会在 TLS 握手阶段
失败，这意味着 `onReceivedSslError` 回调不会被触发，应用无法自行恢复。

若点击悬浮按钮无响应，请检查 `server/watchctl.py` 中的 `WATCH_ADDR` 是否正确，以及
手表是否已启用网络调试。

若状态指示为红色，则为密钥不正确或服务不可达。

```bash
curl -k https://你的服务器:8788/api/watch/points
# 401 表示密钥不匹配
# 超时表示网络不通
```

## 许可证

本项目基于 [MIT 许可证](LICENSE) 发布。

```
Copyright (c) 2026 watch-control contributors
```
