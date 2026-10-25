# Watch Control

> **English** | [中文](README.zh.md)

## Overview

Watch Control lets you pick coordinates on a screenshot of your Android watch,
save them to a small relay service, and then tap them from a floating overlay on
the watch itself.

It is useful when a watch screen is too small to reliably hit certain buttons:
you select the spot on a desktop screen where you can see it clearly, and the
watch gets a corresponding button.

The project is a technical demonstration and reference implementation. It
covers Android overlay windows, the ADB debugging interface, WebView ↔ native
bridging, HMAC request signing, and trusting self-signed certificates inside an
Android app.

## What you need

| Item | Notes |
|---|---|
| An Android watch | With ADB debugging enabled and wireless debugging on |
| A computer | Runs the desktop picker; has Node? no — just Python 3.9+ and `adb` |
| A relay machine | Can be the same computer; a Raspberry Pi works well for always-on use |

Python 3.9 or newer is required. No third-party packages: everything uses the
standard library.

## Quick start

### 1. Generate a pairing key

```bash
./run.sh setup          # Linux / macOS
run.bat setup           # Windows
```

Or manually:

```bash
mkdir -p ~/.config/watch-control
python3 -c "import secrets; print(secrets.token_hex(32))" \
  > ~/.config/watch-control/pairing.key
chmod 600 ~/.config/watch-control/pairing.key
```

### 2. Start the relay service

```bash
./run.sh                # listens on 127.0.0.1:8787
```

The service prints its configuration on startup. Watch address is optional —
the service learns it automatically from the watch's first request.

### 3. Enable ADB on the watch

```bash
adb devices                  # should show "device", not "unauthorized"
adb tcpip 5555               # enable network debugging
adb connect <watch-ip>:5555  # verify
```

The watch shows an authorization prompt the first time — tap **Allow**.

### 4. Build and install the watch app

```bash
cd android
python get_tools.py          # downloads build-tools and android.jar
# Edit MainActivity.java: set BASE_URL, TOKEN, KEY
python compile.py
adb install -r watch-control.apk
```

If the relay runs on this computer and you connect over USB, you can point
`BASE_URL` at your machine's LAN address:

```java
private static final String BASE_URL = "https://192.168.1.100:8787";
```

For a self-signed HTTPS certificate, place it at `res/raw/pi_cert.pem`.
`network_security_config.xml` already references it. Re-package the APK
whenever the certificate changes.

### 5. Start the picker

```bash
./run.sh picker
```

Open <http://127.0.0.1:8765>. The left side shows a live screenshot of the
watch. Click a spot, name it, press **Record this point**. When you are done,
press **Save points** — the coordinates are written locally and pushed to the
relay service.

### 6. Use it on the watch

Open the app on the watch and tap the floating handle. A ring of buttons
appears; tapping one sends the stored coordinate to the relay, which injects it
back into the watch.

## Configuration

All settings are environment variables. Defaults are sensible; you only need to
set what differs.

| Variable | Default | Description |
|---|---|---|
| `WC_HOME` | `~/.config/watch-control` | Where the key and points are stored |
| `WATCH_ADDR` | auto-learned | `ip:port` of the watch; learned from requests |
| `PAIRING_KEY` | from `pairing.key` | Shared secret used to sign requests |
| `ADB_PATH` | `adb` | Path to the adb binary |
| `WC_DEFAULT_DPI` | `120` | Density used by the "reset to my DPI" action |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | Relay listen address |

| Variable | Default | Description |
|---|---|---|
| `BILIAUTO_SERVER` | `http://127.0.0.1:8787` | Relay address for the picker |
| `BILIAUTO_KEY` | from `pairing.key` | Signing key for the picker |
| `BILIAUTO_APP` | empty | Scope points to one package name |
| `ADB_SERIAL` | auto | Device serial for the picker |

## How it works

```
┌─────────────────┐   HMAC-signed HTTP  ┌──────────────┐
│ Desktop browser │ ──────────────────> │ Relay service│
│   picker page   │   push on save      │  (Pi / PC)   │
└─────────────────┘                     └──────┬───────┘
                                               │ adb
                                               │
                                        ┌──────▼───────┐
                                        │    Watch     │
                                        │  (screen)    │
                                        └──────┬───────┘
                                               │ overlay
                                        ┌──────▼───────┐
                                        │Buttons on it │
                                        └──────────────┘
```

The picker captures the watch over adb, writes coordinates, and pushes them to
the relay. The watch app draws the overlay and, when a button is pressed,
reports the coordinate back to the relay, which injects a tap at the same
position on the watch.

## Security

Requests are signed with HMAC-SHA256 in the `X-Bili-Sign` header:

```
HMAC-SHA256(pairing_key, METHOD + "\n" + PATH + "\n" + BODY)  as hex
```

The key is the 64 ASCII characters in `pairing.key`, not the 32 bytes obtained
by hex-decoding it. The path excludes the query string.

The relay listens on `127.0.0.1` by default. Binding it publicly without a
reverse proxy and TLS is not recommended.

The watch address is learned from incoming requests, which lets it follow
dynamic IPv6 reassignment on cellular networks. If you prefer a fixed address,
set `WATCH_ADDR` and it will be used when no request has arrived yet.

## Known limitations

The overlay cannot cover the system UI or full-screen apps that opt out of
overlays. Some vendor ROMs are stricter than stock Android; if the overlay does
not show, check that "Display over other apps" is allowed.

Changing display density changes the logical screen size. The floating handle
is clamped back into range rather than snapped to an edge.

On WebView versions older than 90, `crypto.subtle` is unavailable in insecure
contexts. The watch app derives its signature through a Java bridge instead, so
this only matters if you remove that bridge.

## Troubleshooting

**The watch app stays on "connecting".**
The certificate is probably missing from the APK. A self-signed certificate
fails during the TLS handshake, so `onReceivedSslError` never fires. Check that
`res/raw/pi_cert.pem` exists and rebuild.

**Tapping a button does nothing.**
`WATCH_ADDR` is wrong or network debugging is off. Run `adb devices` on the
relay machine; the watch should appear as `device`.

**Points do not appear in the overlay.**
Press **Save points** in the picker, then refresh the overlay. The picker's
status bar shows whether it reached the relay.

**Requests return 401.**
The key is wrong. Compare `pairing.key` on the relay with the value the picker
uses.

## License

Released under the [MIT License](LICENSE).

```
Copyright (c) 2026 watch-control contributors
```
