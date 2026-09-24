# -*- coding: utf-8 -*-
"""
磁盘 + 数据库体检
1) C 盘到底被什么吃掉了（按文件夹算实际占用，不猜）
2) 有没有残留的 xuangu 副本还留在 C 盘
3) E 盘的数据库是不是完好、能不能接着建
只读不删。要删什么，脚本会告诉你，由你自己动手。
"""
import os, sys, json, time, sqlite3, shutil

本目录 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(本目录, "data", "ashare.db")
输出目录 = os.path.join(本目录, "output")
os.makedirs(输出目录, exist_ok=True)

结果 = {"时间": time.strftime("%Y-%m-%d %H:%M:%S")}
日志 = []


def say(s=""):
    print(s, flush=True)
    日志.append(s)


def GB(b):
    return b / 1024 ** 3


def 目录大小(路径, 时限=90):
    """返回 (字节数, 是否算完)。带时限，避免在超大目录里卡死。"""
    总 = 0
    起 = time.time()
    栈 = [路径]
    完整 = True
    while 栈:
        if time.time() - 起 > 时限:
            完整 = False
            break
        当前 = 栈.pop()
        try:
            with os.scandir(当前) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            栈.append(e.path)
                        else:
                            总 += e.stat(follow_symlinks=False).st_size
                    except (OSError, PermissionError):
                        pass
        except (OSError, PermissionError):
            pass
    return 总, 完整


# ---------------------------------------------------------------- 1. 磁盘剩余
say("=" * 62)
say("  第 1 项  各磁盘剩余空间")
say("=" * 62)
盘面 = {}
for 盘 in ["C:\\", "D:\\", "E:\\", "F:\\"]:
    try:
        u = shutil.disk_usage(盘)
    except OSError:
        continue
    盘面[盘[0]] = {"总GB": round(GB(u.total), 1), "已用GB": round(GB(u.used), 1), "可用GB": round(GB(u.free), 1)}
    say(f"  {盘}  总 {GB(u.total):6.1f} GB   已用 {GB(u.used):6.1f} GB   可用 {GB(u.free):6.1f} GB")
结果["磁盘"] = 盘面
say()

# ---------------------------------------------------------------- 2. 回收站
say("=" * 62)
say("  第 2 项  回收站（跨盘移动时，原件会先进回收站）")
say("=" * 62)
回收站 = {}
for 盘 in ["C:", "D:", "E:", "F:"]:
    路径 = 盘 + "\\$Recycle.Bin"
    if not os.path.isdir(路径):
        路径 = 盘 + "\\$RECYCLE.BIN"
    if not os.path.isdir(路径):
        continue
    大小, 完整 = 目录大小(路径, 时限=60)
    回收站[盘] = round(GB(大小), 2)
    标 = "" if 完整 else "  (目录太大，只算了一部分，实际更多)"
    say(f"  {盘}\\$Recycle.Bin   {GB(大小):8.2f} GB{标}")
结果["回收站GB"] = 回收站
if 回收站.get("C:", 0) > 0.5:
    say()
    say(f"  >>> C 盘回收站占了 {回收站['C:']:.2f} GB。")
    say("  >>> 这就是你 C 盘空间没回来的原因：Windows 跨盘移动 = 先复制再删除，")
    say("  >>> 删掉的原件全进了回收站，空间并没有真正释放。")
    say("  >>> 处理办法：桌面右键「回收站」→ 清空回收站。（脚本不替你删）")
say()

# ---------------------------------------------------------------- 3. C 盘大户
say("=" * 62)
say("  第 3 项  C 盘空间被谁占了（逐个文件夹实测，会花几分钟）")
say("=" * 62)
家 = os.path.expanduser("~")
候选 = []
try:
    with os.scandir(家) as it:
        for e in it:
            if e.is_dir(follow_symlinks=False):
                候选.append(e.path)
except OSError:
    pass
for 额外 in [r"C:\Windows\SoftwareDistribution\Download", r"C:\Windows\Temp",
             r"C:\ProgramData", r"C:\Program Files", r"C:\Program Files (x86)",
             r"C:\Windows\Installer"]:
    if os.path.isdir(额外):
        候选.append(额外)

大户 = []
for i, 路径 in enumerate(候选, 1):
    名 = 路径
    say(f"  [{i}/{len(候选)}] 正在统计 {名} ...")
    大小, 完整 = 目录大小(路径, 时限=45)
    大户.append({"路径": 路径, "GB": round(GB(大小), 2), "算完": 完整})
大户.sort(key=lambda x: -x["GB"])
结果["C盘大户"] = 大户
say()
say("  —— 从大到小（只列 >0.3 GB 的）——")
for x in 大户:
    if x["GB"] >= 0.3:
        标 = "" if x["算完"] else "  (还没算完，实际更大)"
        say(f"    {x['GB']:8.2f} GB   {x['路径']}{标}")
say()

# ---------------------------------------------------------------- 4. 残留副本
say("=" * 62)
say("  第 4 项  C 盘还有没有 xuangu 的残留副本")
say("=" * 62)
残留 = []
搜索根 = [家, r"C:\Users\Public", r"C:\ProgramData"]
起 = time.time()
for 根 in 搜索根:
    if not os.path.isdir(根):
        continue
    for 当前, 子目录, 文件 in os.walk(根):
        if time.time() - 起 > 60:
            break
        # 别往深渊里钻
        深度 = 当前.count(os.sep) - 根.count(os.sep)
        if 深度 > 4:
            子目录[:] = []
            continue
        for d in list(子目录):
            if d.lower() == "xuangu":
                路径 = os.path.join(当前, d)
                大小, _ = 目录大小(路径, 时限=30)
                残留.append({"路径": 路径, "GB": round(GB(大小), 2)})
结果["C盘残留"] = 残留
if 残留:
    for x in 残留:
        say(f"  ！ 找到残留：{x['路径']}   {x['GB']:.2f} GB")
    say("  >>> 确认 E 盘那份没问题之后，把上面这些文件夹删掉（并清空回收站）。")
else:
    say("  干净。C 盘没有 xuangu 的残留副本。")
say()

# ---------------------------------------------------------------- 5. 数据库体检
say("=" * 62)
say("  第 5 项  E 盘数据库完好吗、能不能接着建")
say("=" * 62)
库 = {"路径": DB}
if not os.path.exists(DB):
    say(f"  ！ 找不到数据库：{DB}")
    库["存在"] = False
else:
    库["存在"] = True
    库["大小GB"] = round(GB(os.path.getsize(DB)), 2)
    say(f"  文件：{DB}")
    say(f"  大小：{库['大小GB']} GB")
    wal = DB + "-wal"
    if os.path.exists(wal):
        say(f"  另有未合并的日志 ashare.db-wal  {GB(os.path.getsize(wal)):.2f} GB（正常，下面会合并）")
    try:
        c = sqlite3.connect(DB, timeout=60)
        say("  正在合并日志（wal_checkpoint）...")
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        say("  正在做完整性检查（quick_check，大库要等一两分钟）...")
        检 = c.execute("PRAGMA quick_check").fetchone()[0]
        库["完整性"] = 检
        say(f"  完整性：{检}")

        表 = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        库["表"] = {}
        for t in sorted(表):
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception as e:
                n = f"读不出来: {e}"
            库["表"][t] = n
            say(f"    表 {t:12s} {n:>12,} 行" if isinstance(n, int) else f"    表 {t:12s} {n}")

        # 进度
        if "progress" in 表:
            say()
            say("  —— 建库进度 ——")
            进度 = {}
            for task, st, n in c.execute(
                    "SELECT task, status, COUNT(*) FROM progress GROUP BY task, status"):
                进度.setdefault(task, {})[st] = n
            库["进度"] = 进度
            名字 = {"day": "日线行情", "fin": "财务数据", "div": "分红数据", "ind": "行业分类"}
            for task, d in 进度.items():
                成 = d.get("ok", 0)
                败 = d.get("fail", 0)
                say(f"    {名字.get(task, task):8s} 已完成 {成:>6,}   失败 {败:>5,}")

        # 日线覆盖
        if "daily" in 表:
            say()
            n股 = c.execute("SELECT COUNT(DISTINCT code) FROM daily").fetchone()[0]
            起止 = c.execute("SELECT MIN(date), MAX(date) FROM daily").fetchone()
            库["日线股票数"] = n股
            库["日线区间"] = list(起止)
            say(f"  日线：{n股:,} 只股票，{起止[0]} ~ {起止[1]}")
        c.close()
    except Exception as e:
        库["错误"] = str(e)
        say(f"  ！ 打开数据库出错：{e}")
结果["数据库"] = 库
say()

# ---------------------------------------------------------------- 结论
say("=" * 62)
say("  结论")
say("=" * 62)
c可用 = 盘面.get("C", {}).get("可用GB", 0)
e可用 = 盘面.get("E", {}).get("可用GB", 0)
say(f"  C 盘还剩 {c可用} GB，E 盘还剩 {e可用} GB。")
if 回收站.get("C:", 0) > 0.5:
    say(f"  清空回收站可以立刻拿回约 {回收站['C:']:.1f} GB。")
if 残留:
    总残 = sum(x["GB"] for x in 残留)
    say(f"  删掉残留副本还能再拿回约 {总残:.1f} GB。")
say()
say("  项目现在完全跑在 E 盘，以后建库、回测产生的文件都只会写 E 盘。")
say()

with open(os.path.join(输出目录, "磁盘检查结果.json"), "w", encoding="utf-8") as f:
    json.dump(结果, f, ensure_ascii=False, indent=2)
with open(os.path.join(输出目录, "磁盘检查日志.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(日志))
say("  结果已存到 output\\磁盘检查结果.json —— 把这个文件发给 Claude。")
