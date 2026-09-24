# -*- coding: utf-8 -*-
"""
每日增量更新
============
只补「数据库最后一天」到「今天」之间缺的那几天，不重下历史。

回答两个常问的问题：
  · 要不要删掉旧数据？—— 不要。历史越长，因子窗口和回测越可靠，
    而且一天全市场行情只有约 0.5 MB，一年约 130 MB。你 E 盘还有 250 GB。
    删历史唯一的后果是让回测变短、结论变弱。
  · 多久更新一次？—— 按你的调仓频率来。季度调仓的话，调仓前跑一次就够；
    想每天看持仓分析，就每天收盘后（15:30 之后）跑一次，通常 1-3 分钟。

做了哪些事：
  1. 刷新股票名录（抓新上市 / 新退市）
  2. 只补日线缺的那几天；新上市的股票补完整历史
  3. 刷新最近两个报告期的财务与分红（财报会修订、分红方案会推进）
  4. 刷新指数与国债
"""
import os, sys, time, json, sqlite3
import numpy as np
import pandas as pd

这里 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 这里)
import build_db as B

ROOT = os.path.dirname(这里)
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)


def 主():
    t0 = time.time()
    B.日志.clear()
    say, bar = B.say, B.bar

    bar("=")
    say("   A股选股工具 · 每日增量更新")
    bar("=")
    say()

    if not os.path.exists(B.DB):
        say(f"  找不到数据库 {B.DB}")
        say("  这是增量更新，需要先有一个完整的库。请先跑 02_build_database.bat。")
        return

    c = B.open_db()
    最新 = c.execute("SELECT MAX(date) FROM daily").fetchone()[0]
    今天 = B.结束日期
    say(f"  数据库最新交易日：{最新}")
    say(f"  今天：            {今天}")
    if 最新 and 最新 >= 今天:
        say()
        say("  ✓ 已经是最新的，不用更新。")
        say("    （注意：当天要等收盘后数据才会出来，一般 15:30 之后跑才有今天的K线）")
        c.close()
        return
    say()

    # ---------- 1. 刷新名录 ----------
    bar()
    say("第 1 步  刷新股票名录（找新上市 / 新退市）")
    bar()
    旧数 = c.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
    c.execute("DELETE FROM progress WHERE task='basic'")
    c.commit()
    B.bs_login()
    B.任务_股票名录(c)
    新数 = c.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
    say(f"  名录 {旧数:,} → {新数:,} 条（{新数-旧数:+,}）")
    say()

    # ---------- 2. 补日线 ----------
    bar()
    say("第 2 步  补日线")
    bar()
    codes = B.取股票列表(c)
    已有 = {r[0]: r[1] for r in
            c.execute("SELECT code, MAX(date) FROM daily GROUP BY code")}
    起点 = (pd.Timestamp(最新) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    待办, 新股 = [], []
    for x in codes:
        末 = 已有.get(x)
        if 末 is None:
            新股.append(x)
            待办.append((x, B.起始日期, 今天))       # 新上市 → 补完整历史
        elif 末 < 今天:
            待办.append((x, (pd.Timestamp(末) + pd.Timedelta(days=1)
                             ).strftime("%Y-%m-%d"), 今天))
    say(f"  股票池 {len(codes):,} 只")
    say(f"  需要补 {len(待办):,} 只，其中新上市（补完整历史）{len(新股):,} 只")
    say(f"  增量区间 {起点} ~ {今天}")
    if 新股:
        say(f"    新上市：{', '.join(新股[:12])}{' …' if len(新股) > 12 else ''}")
    say()

    if 待办:
        import multiprocessing as mp
        import mp_fetch
        名表 = dict(c.execute("SELECT code, name FROM stock_basic"))

        def 写入日线(code, rows, fields):
            """和 build_db.任务_日线 里那个同名局部函数完全一致的写法。
            那个是嵌套函数、模块外调不到，所以这里重写一份，
            字段顺序必须和 daily 表的列序严格对应。"""
            idx = {name: k for k, name in enumerate(fields)}

            def f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            def i(v):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None

            buf = [(code, row[idx["date"]],
                    f(row[idx["open"]]), f(row[idx["high"]]),
                    f(row[idx["low"]]), f(row[idx["close"]]),
                    f(row[idx["volume"]]), f(row[idx["amount"]]),
                    f(row[idx["turn"]]), f(row[idx["pctChg"]]),
                    i(row[idx["tradestatus"]]), i(row[idx["isST"]]))
                   for row in rows]
            if buf:
                c.executemany("INSERT OR REPLACE INTO daily "
                              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", buf)
            return len(buf)

        新增行, 失败 = 0, 0
        池 = None
        try:
            池 = mp.Pool(processes=B.并发进程数,
                         initializer=mp_fetch.初始化子进程)
            完成 = 0
            for code, rows, fields, err, dt in 池.imap_unordered(
                    mp_fetch.取日线, 待办, chunksize=1):
                完成 += 1
                if rows is None:
                    失败 += 1
                    状态 = "失败"
                elif len(rows) == 0:
                    状态 = "无新数据"      # 停牌或本来就没交易，增量场景下正常
                else:
                    n = 写入日线(code, rows, fields)
                    新增行 += n
                    状态 = f"{n}根"
                if 完成 % 50 == 0 or 完成 == len(待办):
                    用 = time.time() - t0
                    剩 = 用 / 完成 * (len(待办) - 完成)
                    say(f"  [{完成:>5}/{len(待办)}] {code} "
                        f"{(名表.get(code) or '')[:6]:<7}{状态:<10}"
                        f"已用 {int(用)}秒  "
                        f"剩约 {int(剩)}秒")
                if 完成 % 200 == 0:
                    c.commit()
        finally:
            if 池:
                池.close(); 池.join()
            c.commit()
        say()
        say(f"  ✓ 新增 {新增行:,} 行日线，失败 {失败} 只")
    say()

    # ---------- 3. 刷新最近两个报告期的财务与分红 ----------
    bar()
    say("第 3 步  刷新最近两个报告期的财务与分红")
    say("        （财报会修订、分红方案会从预案推进到实施，所以要重取）")
    bar()
    期全 = B.报告期列表()
    重取 = 期全[-2:]
    for p in 重取:
        c.execute("DELETE FROM progress WHERE task='fin' AND key=?", (p,))
    年期 = [x for x in 期全 if x[:4] >= str(int(今天[:4]) - 1)]
    for p in 年期:
        c.execute("DELETE FROM progress WHERE task='div' AND key=?", (p,))
    c.commit()
    say(f"  财务重取：{重取}")
    say(f"  分红重取：{年期}")
    say()
    try:
        B.任务_财务(c, "全量")
    except Exception as e:
        say(f"  财务更新出错（不影响已有数据）：{e}")
    try:
        B.任务_分红(c, "全量")
    except Exception as e:
        say(f"  分红更新出错（不影响已有数据）：{e}")

    # ---------- 4. 指数、国债、行业 ----------
    bar()
    say("第 4 步  刷新指数 / 国债 / 行业快照")
    bar()
    c.execute("DELETE FROM progress WHERE task='idx'")
    c.execute("DELETE FROM progress WHERE task='bond'")
    c.execute("DELETE FROM progress WHERE task='ind' AND key='当前'")
    c.commit()
    for fn, 名 in ((B.任务_指数, "指数"), (B.任务_国债, "国债")):
        try:
            fn(c)
        except Exception as e:
            say(f"  {名}更新出错（不影响已有数据）：{e}")
    try:
        B.任务_行业(c, "全量")
    except Exception as e:
        say(f"  行业更新出错：{e}")

    # ---------- 汇总 ----------
    bar("=")
    say("更新完成")
    bar("=")
    末 = c.execute("SELECT MAX(date) FROM daily").fetchone()[0]
    行 = c.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    只 = c.execute("SELECT COUNT(DISTINCT code) FROM daily").fetchone()[0]
    大小 = os.path.getsize(B.DB) / 1024 ** 3
    say(f"  最新交易日   {最新}  →  {末}")
    say(f"  日线总行数   {行:,}")
    say(f"  覆盖股票     {只:,} 只")
    say(f"  数据库大小   {大小:.2f} GB")
    say(f"  用时         {int(time.time()-t0)} 秒")
    say()
    say("  历史数据一行都没删 —— 也不该删。")
    say("  一天全市场行情约 0.5 MB，一年约 130 MB；删历史只会让回测变短、结论变弱。")
    say()
    out = {"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
           "更新前最新日": 最新, "更新后最新日": 末,
           "日线行数": 行, "股票数": 只, "数据库GB": round(大小, 2),
           "耗时秒": round(time.time() - t0, 1)}
    with open(os.path.join(OUT, "更新结果.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "更新日志.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(str(x) for x in B.日志))
    c.close()


if __name__ == "__main__":
    try:
        主()
    except KeyboardInterrupt:
        print("\n  已中断。进度都存好了，下次接着跑。")
    except Exception:
        import traceback
        traceback.print_exc()
    if not os.environ.get("XUANGU_NO_PAUSE"):
        input("\n  按回车关闭。")
