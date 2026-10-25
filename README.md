# Watch Control

> **English** | [中文](README.zh.md)

> ## ⚠️ Technical demo — use at your own risk
>
> **This is a technical demonstration project, for learning and research only.
> It is not a product ready for use.**
>
> Using it involves ADB debugging, changing screen density, injecting touch
> events, and installing third-party apps. **It may damage your device, cause
> data loss, void your warranty, or get your accounts banned.**
>
> **You bear all consequences. The author accepts no liability.**
>
> Do not use this on devices you do not own. Do not use it to violate any law
> or any platform's terms of service.
>
> Licensed under [MIT](#license) — use it however you like, at your own risk.

Pick coordinates in a desktop browser → sync them to a server → tap them from a
floating overlay on your Android watch.

Techniques demonstrated: Android overlay windows, the ADB debugging interface,
WebView ↔ native code bridging, HMAC request signing, and trusting self-signed
certificates on Android.

---

## Structure

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

| Dir | What | Runs on |
|---|---|---|
| `android/` | Watch app — floating buttons, forwards taps | Watch |
| `tap-tool/` | Picker — screenshots, records coordinates | Desktop |
| `server/` | Relay — point storage, ADB control | Pi / NAS |

## Setup

Every value that belongs to **you** is a placeholder. **Nothing works until
you replace them.**

### Placeholders

| Placeholder | Where | How to get it |
|---|---|---|
| `YOUR_SERVER_IPV6` | `android/MainActivity.java`<br>`android/res/xml/network_security_config.xml` | `ip -6 addr show scope global` on the server |
| `YOUR_WATCH_TOKEN` | `android/MainActivity.java` | `python3 -c "import secrets; print(secrets.token_hex(12))"` |
| `YOUR_PAIRING_KEY` | `android/MainActivity.java` | `cat ~/.config/biliauto/pairing.key` |
| `YOUR_SERVER_HOST` | `tap-tool/env.sh` | Same IP, no brackets |
| `YOUR_DEVICE_SERIAL` | env `ADB_SERIAL` | `adb devices` (optional) |
| `WATCH_IPV6` | `server/watchctl.py` | `adb shell ip -6 addr show` — the **watch's** IP |

### 1. Generate a pairing key

```bash
mkdir -p ~/.config/biliauto
python3 -c "import secrets; print(secrets.token_hex(32))" \
  > ~/.config/biliauto/pairing.key
chmod 600 ~/.config/biliauto/pairing.key
```

### 2. Enable ADB on the watch

```bash
adb devices                  # should show "device", not "unauthorized"
adb tcpip 5555               # listen over the network
adb connect <watch-ip>:5555  # test
```

The watch shows an authorization prompt the first time — tap **Allow**.

### 3. Bundle the certificate

If your server uses a self-signed HTTPS certificate:

```bash
cp server.crt android/res/raw/pi_cert.pem
```

The filename **must** be `pi_cert.pem`. `network_security_config.xml` already
references it. **Re-package the APK whenever the certificate changes.**

With a public CA (Let's Encrypt etc.), skip this — the system trust store is
already consulted.

### 4. Build the watch app

```bash
cd android
# Edit MainActivity.java: set BASE_URL, TOKEN, KEY
python compile.py
adb install -r watch-control.apk
```

### 5. Run the picker

```bash
cd tap-tool
export ADB_PATH=/path/to/adb
export ADB_SERIAL=your_watch_serial
export BILIAUTO_SERVER=https://your-server:8788
export BILIAUTO_KEY=$(cat ~/.config/biliauto/pairing.key)
python serve.py
```

Open <http://127.0.0.1:8765>.

### 6. Add points

1. Left side shows a live screenshot (refreshed every second)
2. Click the spot you want to tap
3. Name it, hit **Record this point**
4. When done, hit **Save points**

Saving writes the local `points.json` and POSTs to `/api/watch/points`.
Refresh the overlay on the watch and the new buttons appear.

Verify your config:

```bash
python check_config.py     # lists every unreplaced placeholder
```

## Picker features

| Feature | Description |
|---|---|
| Live screenshot | Every second, ~350 ms latency |
| Tap preview | Click a recorded point to verify it |
| Quick buttons | One button per point |
| DPI control | 320 / 120 / 100 / reset |
| Auto-sync | Pushes to the server on save |
| Per-app points | `BILIAUTO_APP` scopes points to one package |

## Watch app interaction

- A small ball (≡) starts at the **center**, draggable, no edge snapping
- **Tap it** to expand the ring of buttons
- **Buttons sit evenly around a circle**; more buttons shrink the radius. Max 10
  per ring, extras go to an inner ring
- **Tap outside** to collapse; the ball returns to where it was
- **Collapsed, the window is 48 dp** and does not intercept other apps' touches

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ADB_PATH` | `adb` | Path to the adb binary |
| `ADB_SERIAL` | auto | Target device serial |
| `BILIAUTO_SERVER` | `https://YOUR_SERVER_HOST:8788` | Server address |
| `BILIAUTO_KEY` | empty | Pairing key; sync off if empty |
| `BILIAUTO_APP` | empty | Package the points belong to |

## Security

**Both links use HTTPS.** The picker ships an SSL context accepting self-signed
certificates (`ssl.CERT_NONE`), so it works against your own server without a
public CA.

Every request carries an HMAC-SHA256 signature in `X-Bili-Sign`:

```
HMAC-SHA256(pairing_key, METHOD + "\n" + PATH + "\n" + BODY)  as hex
```

- `pairing_key` is the **64 ASCII characters** in `pairing.key` — not the 32
  bytes after hex-decoding
- `PATH` excludes the query string
- `chmod 600` the key file

The picker listens on **127.0.0.1 only**. The overlay permission must be granted
manually.

## Known limitations

- On old WebViews (e.g. 83), `crypto.subtle` is unavailable outside secure
  contexts. Signing prefers the Java bridge, with a pure-JS SHA-256 fallback
- Changing DPI changes logical screen size; the ball is re-clamped (not snapped)
  afterward
- When the watch screen sleeps, the app is backgrounded and the page stops
  refreshing

## Troubleshooting

**Watch app stuck on "connecting"**
→ Certificate not bundled. Check `android/res/raw/pi_cert.pem` exists and that
you rebuilt the APK. A self-signed certificate fails at the TLS handshake, so
`onReceivedSslError` never fires.

**Tapping a button does nothing**
→ `WATCH_ADDR` in `server/watchctl.py` is wrong, or watch network debugging is
off.

**Status bar shows a red dot**
→ Key wrong or server unreachable:

```bash
curl -k https://your-server:8788/api/watch/points
# 401 = reachable, key wrong
# timeout = unreachable
```

## Disclaimer

See the warning at the top. In short:

- **Technical demo, not a product.** No support, no warranty, no maintenance.
- **All risk is yours.** Device damage, data loss, voided warranty, account
  bans, legal liability — you own every bit of it.
- **Use only on devices you own**, for lawful purposes, in compliance with
  applicable law and platform terms.
- **Not affiliated** with OPPO, Tencent, Google, or any other company. All
  trademarks belong to their owners.
- **This text is informational.** It creates no obligation on the author and is
  not legal advice.

## License

[MIT](LICENSE) — do whatever you want, including commercial use, at your own
risk. The MIT warranty disclaimer applies in full.

```
Copyright (c) 2026 watch-control contributors
```
