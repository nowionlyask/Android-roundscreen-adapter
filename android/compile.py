#!/usr/bin/env python3
"""编译 Java -> dex -> 打包 APK。

流程：javac 编译 -> d8 转 dex -> build_apk.py 打包签名
"""
import shutil
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
BT = WS / "tools" / "bt" / "android-11"
PLATFORM = WS / "tools" / "pf" / "android-11" / "android.jar"
BUILD = WS / "build"
CLS = BUILD / "classes"


def run(cmd, label, check=True):
    print(f"=== {label} ===")
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       shell=isinstance(cmd, str))
    if r.returncode != 0:
        print("  [失败] 返回码", r.returncode)
        print("  STDERR:", r.stderr[:1500])
        print("  STDOUT:", r.stdout[:800])
        if check:
            sys.exit(1)
        return False
    if r.stdout.strip():
        print("  ", r.stdout.strip()[:400])
    return True


def main():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    CLS.mkdir(parents=True)

    # 1. javac
    java_files = sorted(WS.glob("*.java"))
    print(f"源文件: {[f.name for f in java_files]}")
    cmd = [
        "javac",
        "-source", "8", "-target", "8",
        "-bootclasspath", str(PLATFORM),
        "-encoding", "UTF-8",
        "-d", str(CLS),
        *[str(f) for f in java_files],
    ]
    run(cmd, "javac 编译")

    # 2. d8 -> dex
    class_files = list(CLS.rglob("*.class"))
    print(f"编译产物: {len(class_files)} 个 class")
    d8 = BT / "d8.bat"
    dex_out = WS / "classes.dex"
    if dex_out.exists():
        dex_out.unlink()
    run([str(d8), "--output", str(WS), "--lib", str(PLATFORM),
         *[str(c) for c in class_files]], "d8 转 dex")
    if not dex_out.exists():
        print("[失败] classes.dex 没生成")
        return 1
    print(f"classes.dex: {dex_out.stat().st_size} 字节")

    # 3. 打包
    run([sys.executable, str(WS / "build_apk.py")], "打包 APK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
