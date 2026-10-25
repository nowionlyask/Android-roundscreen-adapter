#!/usr/bin/env python3
"""在 Windows 上完成 APK 打包（aapt2 link + 加 dex + zipalign + 签名）。

用 Python 编排，避开 cmd 批处理的编码/引号问题。
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

WS = Path(r"C:\Users\wcx\RaspBerryPi\biliremote\android")
BT = WS / "tools" / "bt" / "android-11"
PLATFORM = WS / "tools" / "pf" / "android-11" / "android.jar"
BUILD = WS / "package"
DEX = WS / "classes.dex"
KS = WS / "keystore.jks"


def run(cmd, label):
    print(f"=== {label} ===")
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print("  STDERR:", r.stderr[:500])
        print("  STDOUT:", r.stdout[:500])
        return False
    if r.stdout.strip():
        print("  ", r.stdout.strip()[:300])
    return True


def main():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    aapt2 = BT / "aapt2.exe"
    zipalign = BT / "zipalign.exe"
    apksigner = BT / "lib" / "apksigner.jar"

    # 1. compile res
    res_zip = BUILD / "res.zip"
    ok = run([str(aapt2), "compile", "--dir", str(WS / "res"), "-o", str(res_zip)], "compile res")
    if not ok:
        return 1

    # 2. link
    base = BUILD / "base.apk"
    ok = run([
        str(aapt2), "link",
        "-I", str(PLATFORM),
        "--manifest", str(WS / "AndroidManifest.xml"),
        "-R", str(res_zip),
        "--min-sdk-version", "21",
        "--target-sdk-version", "30",
        "-o", str(base),
    ], "aapt2 link")
    if not ok or not base.exists():
        return 1
    print(f"   base.apk {base.stat().st_size} bytes")

    # 3. add dex
    print("=== add classes.dex ===")
    app = BUILD / "app.apk"
    shutil.copyfile(base, app)
    with zipfile.ZipFile(app, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("classes.dex", DEX.read_bytes())
    with zipfile.ZipFile(app) as z:
        names = z.namelist()
    print(f"   APK 内容: {names}")
    if "classes.dex" not in names:
        return 1

    # 4. zipalign
    aligned = BUILD / "app_aligned.apk"
    ok = run([str(zipalign), "-f", "-p", "4", str(app), str(aligned)], "zipalign")
    if not ok:
        return 1

    # 5. sign
    signed = BUILD / "biliauto-watch.apk"
    ok = run([
        "java", "-jar", str(apksigner), "sign",
        "--ks", str(KS),
        "--ks-pass", "pass:biliauto123",
        "--key-pass", "pass:biliauto123",
        "--v1-signing-enabled", "true",
        "--v2-signing-enabled", "true",
        "--out", str(signed),
        str(aligned),
    ], "apksigner")
    if not ok or not signed.exists():
        return 1

    print(f"\n=== RESULT ===")
    print(f"   biliauto-watch.apk {signed.stat().st_size} bytes")

    dest = WS.parent / "watch-control.apk"
    shutil.copyfile(signed, dest)
    print(f"   copied -> {dest} ({dest.stat().st_size} bytes)")

    # 验证
    print("\n=== verify ===")
    r = subprocess.run(["java", "-jar", str(apksigner), "verify", "--print-certs", str(signed)],
                       capture_output=True, text=True, errors="replace")
    print(r.stdout.strip()[:400] if r.stdout.strip() else r.stderr[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
