# Watch Control

> **English** | [中文](README.zh.md)

## Overview

Watch Control is a technical demonstration of coordinating a desktop browser, a
small relay server, and an Android watch. It allows a user to select coordinates
on a captured screenshot of the watch, persist those coordinates on a server,
and then invoke them from a floating overlay rendered on the watch itself.

The project serves as a reference implementation for several techniques that are
often useful when working with wearables: Android overlay windows, the ADB
debugging interface, bidirectional communication between a WebView and native
code, HMAC-based request signing, and trusting self-signed certificates within
an Android application.

## Important notes

This is a demonstration project intended for study and experimentation. It is
not a finished product, and it is provided without any guarantee of correctness,
stability, or fitness for a particular purpose.

The techniques demonstrated involve system-level operations — enabling ADB,
adjusting display density, injecting input events, and installing third-party
applications. These operations carry inherent risk. On some devices they may
result in data loss, loss of warranty coverage, or unexpected system behaviour.
If you intend to experiment, please do so on a device you own and can afford to
lose.

Third-party platform automation may also conflict with the terms of service of
those platforms. Please review and respect the applicable agreements before use.

You are responsible for how you use this project. The author does not accept
liability for any consequences arising from its use.

## Architecture

The system consists of three cooperating parts.

```
┌─────────────────┐    HTTPS + HMAC     ┌──────────────┐
│ Desktop browser │ ──────────────────> │    Server    │
│  tap-tool page  │  auto-sync on save  │  (Pi / NAS)  │
└─────────────────┘                     └──────┬───────┘
        │                                      │
        │ USB / adb                            │ ADB over WiFi
        ▼                                      ▼
┌─────────────────┐                     ┌──────────────┐
│ Watch (screen)  │ <─────────────────> │Watch overlay │
└─────────────────┘                     └──────────────┘
```

| Directory | Purpose | Runs on |
|---|---|---|
| `android/` | Watch application; renders the overlay and forwards taps | Watch |
| `tap-tool/` | Desktop tool; captures screenshots and records coordinates | Desktop |
| `server/` | Relay service; stores configuration and issues ADB commands | Pi / NAS |

## Getting started

The repository uses placeholders wherever a value depends on your own
environment. These must be replaced before the system will function.

### Configuration placeholders

| Placeholder | Location | How to obtain |
|---|---|---|
| `YOUR_SERVER_IPV6` | `android/MainActivity.java`, `network_security_config.xml` | `ip -6 addr show scope global` on the server |
| `YOUR_WATCH_TOKEN` | `android/MainActivity.java` | Generate with `secrets.token_hex(12)` |
| `YOUR_PAIRING_KEY` | `android/MainActivity.java` | Contents of `~/.config/biliauto/pairing.key` |
| `YOUR_SERVER_HOST` | `tap-tool/env.sh` | Same address as above, without brackets |
| `YOUR_DEVICE_SERIAL` | `ADB_SERIAL` environment variable | Listed by `adb devices` (optional) |
| `WATCH_IPV6` | `server/watchctl.py` | The watch's own address, from `adb shell ip -6 addr show` |

Running `python check_config.py` will list any placeholders that remain.

### Preparing the server

Generate a pairing key. This value authenticates requests between the watch
application and the relay service.

```bash
mkdir -p ~/.config/biliauto
python3 -c "import secrets; print(secrets.token_hex(32))" \
  > ~/.config/biliauto/pairing.key
chmod 600 ~/.config/biliauto/pairing.key
```

### Preparing the watch

Enable ADB debugging in the watch's developer settings, then confirm the
connection. The watch will display an authorization prompt the first time.

```bash
adb devices                  # expect "device", not "unauthorized"
adb tcpip 5555               # enable network debugging
adb connect <watch-ip>:5555  # verify
```

### Certificates

If the relay service uses a self-signed certificate, place it in the
application resources:

```bash
cp server.crt android/res/raw/pi_cert.pem
```

The filename must remain `pi_cert.pem`, as it is referenced by
`network_security_config.xml`. The APK should be rebuilt whenever the
certificate is regenerated.

If you are using a certificate issued by a public authority, this step can be
skipped, as the system trust store is consulted by default.

### Building the watch application

```bash
cd android
# Set BASE_URL, TOKEN, and KEY in MainActivity.java first
python compile.py
adb install -r watch-control.apk
```

### Running the desktop tool

```bash
cd tap-tool
export ADB_PATH=/path/to/adb
export ADB_SERIAL=your_watch_serial
export BILIAUTO_SERVER=https://your-server:8788
export BILIAUTO_KEY=$(cat ~/.config/biliauto/pairing.key)
python serve.py
```

The interface is then available at <http://127.0.0.1:8765>.

### Recording coordinates

The left-hand side of the interface displays a live capture of the watch,
refreshed approximately once per second. Clicking the image records the
corresponding coordinate; assigning it a name and pressing **Record this point**
adds it to the list. Once the list is complete, **Save points** writes the
configuration locally and synchronises it with the relay service. The overlay on
the watch will reflect the update after it is refreshed.

## Features

The desktop tool provides a live capture of the watch display, adjustable
display density (320, 120, 100, or the system default), the ability to test any
recorded coordinate directly, and automatic synchronisation with the relay
service. Coordinates may be scoped to a specific package using
`BILIAUTO_APP`.

The watch application presents a small draggable handle that expands into a ring
of buttons arranged evenly around a circle. The radius adjusts as more points
are added, with up to ten placed on the outer ring and any additional points on
an inner ring. The handle itself occupies only 48 dp while collapsed, so it does
not interfere with other applications.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ADB_PATH` | `adb` | Path to the adb executable |
| `ADB_SERIAL` | auto-detected | Target device serial |
| `BILIAUTO_SERVER` | `https://YOUR_SERVER_HOST:8788` | Relay service address |
| `BILIAUTO_KEY` | empty | Pairing key; synchronisation is disabled when empty |
| `BILIAUTO_APP` | empty | Package the coordinates belong to |

## Security considerations

Both communication paths use HTTPS. The desktop tool includes an SSL context
that accepts self-signed certificates, which allows it to communicate with a
private relay service that does not have a certificate from a public authority.

Each request carries an HMAC-SHA256 signature in the `X-Bili-Sign` header.

```
HMAC-SHA256(pairing_key, METHOD + "\n" + PATH + "\n" + BODY)  as hex
```

The pairing key consists of the 64 ASCII characters stored in `pairing.key`, not
the 32 bytes that result from interpreting it as hexadecimal. The path excludes
any query string. The key file should be readable only by its owner.

The desktop tool listens on `127.0.0.1` only, and the overlay permission on the
watch must be granted manually by the user.

## Known limitations

Older WebView implementations, such as version 83, do not expose
`crypto.subtle` outside of a secure context. Signing therefore prefers the Java
bridge, with a pure-JavaScript SHA-256 implementation as a fallback.

Changing the display density alters the logical dimensions of the screen, after
which the handle position is clamped back into range rather than snapped to an
edge.

When the watch display sleeps, the application is moved to the background and
the page stops refreshing.

## Troubleshooting

If the watch application remains on "connecting", the certificate is likely
missing from the APK. A self-signed certificate fails during the TLS handshake,
which means the `onReceivedSslError` callback is never reached, so the
application cannot recover on its own.

If tapping an overlay button has no effect, check that `WATCH_ADDR` in
`server/watchctl.py` is correct and that network debugging is enabled on the
watch.

If the status indicator is red, either the key is incorrect or the service is
unreachable.

```bash
curl -k https://your-server:8788/api/watch/points
# 401 indicates a key mismatch
# a timeout indicates a network problem
```

## License

Released under the [MIT License](LICENSE).

```
Copyright (c) 2026 watch-control contributors
```
