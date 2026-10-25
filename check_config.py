#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置自检：检查项目里是否还有没替换的占位符。

用法：
    python check_config.py

在所有占位符都替换成真实值之前，程序跑不起来。这个脚本帮你找出遗漏。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# 需要替换的占位符 -> 说明
PLACEHOLDERS = {
    "YOUR_SERVER_IPV6":  "服务器 IPv6 地址（android/MainActivity.java）",
    "YOUR_SERVER_HOST":  "服务器地址（tap-tool 和 xml 配置）",
    "YOUR_PAIRING_KEY":  "配对密钥（android/MainActivity.java）",
    "YOUR_WATCH_TOKEN":  "网页访问口令（android/MainActivity.java）",
    "YOUR_DEVICE_SERIAL": "设备序列号（tap-tool 环境变量）",
    "YOUR_WATCH_MODEL":  "手表型号（仅注释，可忽略）",
    "WATCH_IPV6":        "手表的 ADB 地址（server/watchctl.py）",
}

# 跳过这些文件和目录（示例文件里保留占位符是正常的）
SKIP_FILES = {
    "check_config.py",
    "SETUP.md",
    "README.md",
    "env.sh.example",
}
SKIP_DIRS = {".git", "__pycache__", "build", "package"}


def should_skip(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return True
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    return False


def main() -> int:
    print("=" * 60)
    print("配置自检")
    print("=" * 60)
    print()

    found: dict[str, list[str]] = {}

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".java", ".py", ".xml", ".sh", ".json"}:
            continue
        if should_skip(path.relative_to(ROOT)):
            continue

        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        rel = str(path.relative_to(ROOT))
        for ph in PLACEHOLDERS:
            if ph in txt:
                found.setdefault(ph, []).append(rel)

    if not found:
        print("✅ 所有占位符都已替换，可以开始使用了")
        print()
        return 0

    print(f"⚠️  发现 {len(found)} 个未替换的占位符：")
    print()

    for ph, files in sorted(found.items()):
        desc = PLACEHOLDERS[ph]
        print(f"  {ph}")
        print(f"    含义：{desc}")
        print(f"    位置：{', '.join(files)}")
        print()

    print("-" * 60)
    print("怎么改？看 SETUP.md，里面有每个占位符的详细说明。")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
