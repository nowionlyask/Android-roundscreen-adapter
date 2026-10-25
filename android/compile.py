#!/usr/bin/env python3
"""编译 Java -> dex -> 打包 APK。

流程：javac 编译 -> dx 转 dex -> build_apk.py 打包签名

依赖：JDK（javac）+ Android build-tools（放在 tools/ 目录下）
跨平台：Windows / Linux / macOS 都可以跑。
"""
import os
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
    print("=== {} ===".format(label))
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
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


def find_java8():
    """dx.jar 在老版本 JDK 上更稳，优先用 Java 8。

    没有就退回系统默认 java（新版 JDK 上 dx 可能会崩，但先试）。
    """
    env = os.environ.get("JAVA8_HOME")
    if env:
        p = Path(env) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if p.exists():
            return str(p)
    return "java"


def main():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    CLS.mkdir(parents=True)

    # 1. javac
    java_files = sorted(WS.glob("*.java"))
    if not java_files:
        print("[失败] 当前目录没有 .java 文件")
        return 1
    print("源文件:", [f.name for f in java_files])

    cmd = [
        "javac",
        "--release", "8",
        "-classpath", str(PLATFORM),
        "-encoding", "UTF-8",
        "-d", str(CLS),
    ]
    cmd += [str(f) for f in java_files]
    run(cmd, "javac 编译")

    # 2. dx -> dex
    class_files = list(CLS.rglob("*.class"))
    print("编译产物: {} 个 class".format(len(class_files)))
    dx = BT / "lib" / "dx.jar"
    if not dx.exists():
        print("[失败] 找不到 tools/bt/android-11/lib/dx.jar")
        return 1

    dex_out = WS / "classes.dex"
    if dex_out.exists():
        dex_out.unlink()

    run([find_java8(), "-cp", str(dx),
         "com.android.dx.command.Main",
         "--dex", "--output={}".format(dex_out)]
        + [str(c) for c in class_files], "dx 转 dex")

    if not dex_out.exists():
        print("[失败] classes.dex 没生成")
        return 1
    print("classes.dex: {} 字节".format(dex_out.stat().st_size))

    # 3. 打包
    run([sys.executable, str(WS / "build_apk.py")], "打包 APK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
