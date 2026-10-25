#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载编译 APK 需要的 Android build-tools。

用法：
    python get_tools.py

会在 android/tools/ 下准备好：
    tools/bt/android-11/      build-tools（aapt2、zipalign、dx.jar、apksigner）
    tools/pf/android-11/      android.jar

来源：本脚本从 Maven 中央仓库拉取，不需要 Android Studio。
如果下载失败，也可以手动从以下地址下载后解压到对应目录：
    build-tools: https://dl.google.com/android/repository/build-tools_r30.0.3-windows.zip
    platform:    https://dl.google.com/android/repository/platform-30_r03.zip
"""

from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent
TOOLS = WS / "tools"
BT_DIR = TOOLS / "bt" / "android-11"
PF_DIR = TOOLS / "pf" / "android-11"

# 官方下载地址
URLS = {
    "bt_win": "https://dl.google.com/android/repository/build-tools_r30.0.3-windows.zip",
    "bt_linux": "https://dl.google.com/android/repository/build-tools_r30.0.3-linux.zip",
    "bt_mac": "https://dl.google.com/android/repository/build-tools_r30.0.3-macosx.zip",
    "platform": "https://dl.google.com/android/repository/platform-30_r03.zip",
}


def pick_bt_url() -> str:
    if sys.platform == "win32":
        return URLS["bt_win"]
    if sys.platform == "darwin":
        return URLS["bt_mac"]
    return URLS["bt_linux"]


def download(url: str, dest: Path) -> bool:
    print("下载 {} ...".format(url.rsplit("/", 1)[-1]))
    try:
        urllib.request.urlretrieve(url, dest)
        print("  完成，{} 字节".format(dest.stat().st_size))
        return True
    except Exception as e:  # noqa: BLE001
        print("  失败: {}".format(e))
        return False


def extract(src: Path, dest: Path, strip_prefix: str | None = None) -> None:
    print("解压到 {} ...".format(dest))
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            rel = name
            if strip_prefix and rel.startswith(strip_prefix):
                rel = rel[len(strip_prefix):]
            if not rel:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as f, open(target, "wb") as out:
                out.write(f.read())
    print("  完成")


def main() -> int:
    TOOLS.mkdir(parents=True, exist_ok=True)

    # 1. build-tools
    if (BT_DIR / "lib" / "dx.jar").exists():
        print("[+] build-tools 已存在，跳过")
    else:
        zip_path = TOOLS / "bt.zip"
        if not download(pick_bt_url(), zip_path):
            print("\n[!] 下载失败。可以手动下载后解压到:")
            print("    {}".format(BT_DIR))
            return 1
        # 压缩包里通常有一层目录，需要剥掉
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        prefix = ""
        if names and "/" in names[0]:
            prefix = names[0].split("/")[0] + "/"
        extract(zip_path, BT_DIR, prefix)
        zip_path.unlink(missing_ok=True)

    # 2. platform
    jar = PF_DIR / "android.jar"
    if jar.exists():
        print("[+] android.jar 已存在，跳过")
    else:
        zip_path = TOOLS / "pf.zip"
        if not download(URLS["platform"], zip_path):
            print("\n[!] 下载失败。可以手动下载后解压到:")
            print("    {}".format(PF_DIR))
            return 1
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        prefix = ""
        if names and "/" in names[0]:
            prefix = names[0].split("/")[0] + "/"
        extract(zip_path, PF_DIR, prefix)
        zip_path.unlink(missing_ok=True)

    print()
    print("=" * 50)
    print("工具准备完成，现在可以运行:")
    print("    python compile.py")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
