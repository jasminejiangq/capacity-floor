# -*- coding: utf-8 -*-
"""
修复 WRDS 连接环境
==================
不装官方 wrds 包（它把 pandas 钉死在 <2.3，Python 3.14 上必须源码编译）。
改为只装一个 PostgreSQL 驱动，按「越不需要编译越优先」的顺序尝试：

    psycopg[binary] → psycopg2-binary → pg8000（纯 Python，保底）

只要有一个成功就够了。pg8000 是纯 Python，不可能因为缺编译器而失败。
"""
import sys, subprocess, importlib, platform


def bar(ch="-"):
    print(ch * 66)


def 跑(*args):
    return subprocess.run([sys.executable, "-m", "pip", *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def 能导入(名):
    try:
        importlib.invalidate_caches()
        importlib.import_module(名)
        return True
    except Exception:
        return False


def 主():
    bar("=")
    print("   修复 WRDS 连接环境")
    bar("=")
    print(f"  Python      {platform.python_version()}  ({platform.architecture()[0]})")
    print(f"  解释器路径   {sys.executable}")
    是venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    print(f"  虚拟环境     {'✓ 在 .venv 里' if 是venv else '⚠ 用的是全局 Python'}")
    if not 是venv:
        print("    注意：你在全局环境里。建议关掉，改用 .bat 启动（它会自动用 .venv）。")
    print()

    # 先确认 pandas 可用 —— 这是不装 wrds 包的前提
    try:
        import pandas as pd
        import numpy as np
        print(f"  pandas      {pd.__version__}   ✓ 已可用，不需要重装")
        print(f"  numpy       {np.__version__}   ✓")
    except Exception as e:
        print(f"  ✗ pandas/numpy 有问题：{e}")
        print("    这个环境连 A 股项目都跑不了，先解决这个再说。")
        return
    print()

    bar()
    print("  开始尝试安装 PostgreSQL 驱动（三选一，装上一个就停）")
    bar()
    候选 = [
        ("psycopg[binary]", "psycopg", "C扩展，最快"),
        ("psycopg2-binary", "psycopg2", "C扩展，最常见"),
        ("pg8000",          "pg8000",   "纯Python，保底，永不需要编译"),
    ]
    成功 = None
    for 包名, 模块名, 说明 in 候选:
        if 能导入(模块名):
            print(f"  ✓ {模块名} 已经装好了（{说明}）")
            成功 = 模块名
            break
        print(f"  → 尝试 {包名}（{说明}）…")
        r = 跑("install", "--only-binary=:all:", 包名)
        if r.returncode == 0 and 能导入(模块名):
            print(f"    ✓ 成功")
            成功 = 模块名
            break
        理由 = ""
        低 = (r.stdout + r.stderr).lower()
        if "no matching distribution" in 低 or "could not find a version" in 低:
            理由 = f"没有 Python {platform.python_version()} 的预编译包"
        elif "vswhere" in 低 or "visual studio" in 低 or "microsoft visual c++" in 低:
            理由 = "需要 Visual Studio C++ 编译器（你没装，也不必装）"
        else:
            理由 = (r.stderr or r.stdout).strip().splitlines()[-1][:110] if (r.stderr or r.stdout) else "未知"
        print(f"    ✗ 不行：{理由}")

    print()
    bar("=")
    if 成功:
        print(f"  ✓ 环境就绪，驱动是 {成功}")
        print()
        print("  下一步：双击 09_WRDS数据自检.bat")
        print("  （第一次连接手机会收到 Duo 推送，点确认）")
    else:
        print("  ✗ 三个驱动都没装上。这很少见，通常是网络问题。")
        print()
        print("  手动试一次，看完整报错：")
        print(f"    \"{sys.executable}\" -m pip install pg8000")
        print()
        print("  pg8000 是纯 Python 的，理论上任何环境都能装。")
        print("  如果它都失败，那是 pip 连不上 PyPI，和 Python 版本无关。")
    bar("=")


if __name__ == "__main__":
    try:
        主()
    except Exception:
        import traceback
        traceback.print_exc()
    import os
    if not os.environ.get("XUANGU_NO_PAUSE"):
        input("\n  按回车关闭。")
