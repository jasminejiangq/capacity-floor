# -*- coding: utf-8 -*-
"""
A股选股工具 — 诊断：把三个悬而未决的问题一次问清楚
=====================================================
不猜，直接问数据。大约 3-6 分钟。

要回答的问题：
  Q1  财务表为什么有 11500 条？（A股只有 5556 只）
  Q2  分红接口真实的列名到底叫什么？
  Q3  行业接口支不支持取历史日期？
  Q4  市值能不能从 volume/turn 精确推导？（省掉额外下载）
  Q5  多进程并发能跑多快？会不会被限流？

输出: output/诊断结果.json
"""

import sys, os, json, time, sqlite3, warnings, traceback
from datetime import datetime

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "ashare.db")
OUT_DIR = os.path.join(ROOT, "output")
os.makedirs(OUT_DIR, exist_ok=True)

R = {"生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
日志 = []


def say(m=""):
    print(m, flush=True)
    日志.append(str(m))


def bar(ch="-"):
    say(ch * 64)


# ============================================================
# Q1  财务表 11500 条之谜（查本地库，不用联网，秒出）
# ============================================================
def Q1_财务异常():
    bar("=")
    say("Q1  财务表为什么有 11500 条？")
    bar("=")
    out = {}
    if not os.path.exists(DB):
        say("  找不到数据库，跳过\n")
        return
    c = sqlite3.connect(DB)

    rows = c.execute("""SELECT report_date, COUNT(*) , COUNT(DISTINCT code)
                        FROM finance GROUP BY report_date
                        ORDER BY report_date""").fetchall()
    say("  报告期        总行数   不同代码数")
    for rd, n, nd in rows:
        say(f"  {rd}     {n:>7,}   {nd:>7,}")
    out["按报告期"] = [{"报告期": r[0], "行数": r[1], "不同代码": r[2]} for r in rows]
    say()

    # 代码长什么样？按长度和前缀分类
    say("  代码长度分布：")
    for ln, n in c.execute("""SELECT LENGTH(code), COUNT(DISTINCT code)
                              FROM finance GROUP BY LENGTH(code)
                              ORDER BY 2 DESC""").fetchall():
        say(f"    长度 {ln} 位 : {n:,} 个")
    out["代码长度"] = c.execute(
        "SELECT LENGTH(code), COUNT(DISTINCT code) FROM finance "
        "GROUP BY LENGTH(code)").fetchall()
    say()

    say("  代码前缀分布（前2位）：")
    pref = c.execute("""SELECT SUBSTR(code,1,2), COUNT(DISTINCT code)
                        FROM finance GROUP BY SUBSTR(code,1,2)
                        ORDER BY 2 DESC LIMIT 20""").fetchall()
    for p, n in pref:
        标 = ""
        if p in ("60", "68"): 标 = "← 沪市"
        elif p in ("00", "30"): 标 = "← 深市"
        elif p in ("83", "87", "92", "43"): 标 = "← 北交所"
        say(f"    {p}xxxx : {n:>6,}  {标}")
    out["代码前缀"] = pref
    say()

    # 关键检验：finance 里的代码有多少能和 stock_basic 对上
    匹配 = c.execute("""
        SELECT COUNT(DISTINCT f.code) FROM finance f
        WHERE EXISTS (SELECT 1 FROM stock_basic b
                      WHERE SUBSTR(b.code,4) = f.code AND b.type='1')
    """).fetchone()[0]
    总 = c.execute("SELECT COUNT(DISTINCT code) FROM finance").fetchone()[0]
    say(f"  finance 中不同代码 {总:,} 个，能对上 A 股名录的 {匹配:,} 个"
        f"（{匹配/max(总,1)*100:.1f}%）")
    out["总代码数"] = 总
    out["能对上A股名录"] = 匹配
    say()

    # 对不上的长什么样
    孤儿 = c.execute("""
        SELECT f.code, f.report_date FROM finance f
        WHERE NOT EXISTS (SELECT 1 FROM stock_basic b
                          WHERE SUBSTR(b.code,4)=f.code AND b.type='1')
        LIMIT 15
    """).fetchall()
    if 孤儿:
        say(f"  对不上的样本：{[x[0] for x in 孤儿]}")
        out["对不上样本"] = [x[0] for x in 孤儿]
    else:
        say("  没有对不上的代码 → 说明 11500 是真实的不同代码")
    say()

    # 那些只在年报/半年报出现的代码，是不是北交所/新三板
    只在年报 = c.execute("""
        SELECT COUNT(DISTINCT code) FROM finance
        WHERE report_date LIKE '%1231' AND code NOT IN
              (SELECT code FROM finance WHERE report_date LIKE '%0930')
    """).fetchone()[0]
    say(f"  只出现在年报期、不出现在三季报期的代码：{只在年报:,} 个")
    out["只在年报期"] = 只在年报
    if 只在年报 > 3000:
        say("  → 高度怀疑：年报期接口把新三板/北交所也返回了，")
        say("    或者 akshare 在该参数下返回了多个市场。建库时必须过滤。")
    say()
    c.close()
    R["Q1_财务异常"] = out


# ============================================================
# Q2  分红接口真实列名
# ============================================================
def Q2_分红列名():
    bar("=")
    say("Q2  分红接口真实的列名是什么？")
    bar("=")
    out = {}

    # 先看本地库里上次失败留下的 note
    if os.path.exists(DB):
        c = sqlite3.connect(DB)
        for task, key, st, note in c.execute(
                "SELECT task,key,status,note FROM progress WHERE task='div'"):
            say(f"  上次记录  {key}  {st}  → {note[:200]}")
            out.setdefault("上次失败记录", []).append({"期": key, "状态": st, "说明": note})
        c.close()
        say()

    try:
        import akshare as ak
    except Exception as e:
        say(f"  AKShare 不可用：{e}\n")
        return

    for 期 in ("20231231", "20241231"):
        say(f"  测试 stock_fhps_em(date='{期}') ...")
        try:
            t0 = time.time()
            df = ak.stock_fhps_em(date=期)
            cols = [str(x) for x in df.columns]
            say(f"    ✓ {len(df)} 行，耗时 {time.time()-t0:.1f}s")
            say(f"    列名（共{len(cols)}个）：")
            for k in range(0, len(cols), 4):
                say("      " + " | ".join(cols[k:k+4]))
            out[期] = {"行数": int(len(df)), "列名": cols}
            # 找出关键字段
            代码列 = [x for x in cols if "代码" in x]
            现金列 = [x for x in cols if "现金" in x or "派息" in x or "分红" in x]
            日期列 = [x for x in cols if "日" in x]
            say(f"    含『代码』的列：{代码列}")
            say(f"    含『现金/分红/派息』的列：{现金列}")
            say(f"    含『日』的列：{日期列}")
            out[期]["代码列"] = 代码列
            out[期]["现金列"] = 现金列
            out[期]["日期列"] = 日期列
            if len(df) > 0:
                out[期]["首行"] = {k: str(v) for k, v in
                                   df.iloc[0].to_dict().items()}
            say()
            break            # 一期成功就够了
        except Exception as e:
            say(f"    ✗ {type(e).__name__}: {e}")
            out[期] = {"错误": f"{type(e).__name__}: {e}"}
            say()

    R["Q2_分红列名"] = out


# ============================================================
# Q3  行业接口能不能取历史日期
# ============================================================
def Q3_历史行业():
    bar("=")
    say("Q3  行业接口支不支持取历史日期？")
    say("    （能的话就不用关闭行业中性化了）")
    bar("=")
    out = {}
    try:
        import baostock as bs
    except Exception as e:
        say(f"  Baostock 不可用：{e}\n")
        return
    bs.login()

    def 取(日期=None):
        rs = bs.query_stock_industry(date=日期) if 日期 else bs.query_stock_industry()
        if rs.error_code != "0":
            raise RuntimeError(f"{rs.error_code}: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return rows, rs.fields

    结果 = {}
    for 日期 in [None, "2015-06-30", "2020-06-30"]:
        标签 = 日期 or "不带日期(当前)"
        try:
            t0 = time.time()
            rows, fields = 取(日期)
            idx = {n: k for k, n in enumerate(fields)}
            更新日 = rows[0][idx["updateDate"]] if rows else "?"
            有行业 = sum(1 for r in rows if r[idx["industry"]])
            say(f"  {标签:<18} ✓ {len(rows):,} 条，updateDate={更新日}，"
                f"有行业标签 {有行业:,}，{time.time()-t0:.0f}s")
            结果[标签] = {"条数": len(rows), "updateDate": 更新日,
                          "有行业": 有行业}
        except Exception as e:
            say(f"  {标签:<18} ✗ {type(e).__name__}: {e}")
            结果[标签] = {"错误": f"{type(e).__name__}: {e}"}

    # 判断：不同日期返回的 updateDate 是否不同
    日期们 = {k: v.get("updateDate") for k, v in 结果.items() if "updateDate" in v}
    唯一 = set(日期们.values())
    say()
    if len(唯一) > 1:
        say("  ✓ 不同日期返回了不同的 updateDate → 支持历史行业快照")
        say("    结论：行业中性化可以正常做，不需要关闭")
        out["支持历史"] = True
    else:
        say("  ○ 不同日期返回的 updateDate 相同 → 只有当前快照")
        say("    结论：行业标签仍可用于『单行业上限30%』，")
        say("          但行业中性化要在回测报告里标注这一局限，")
        say("          并做一次『中性化 / 不中性化』的敏感性对比。")
        out["支持历史"] = False
    out["各日期结果"] = 结果
    say()
    try:
        bs.logout()
    except Exception:
        pass
    R["Q3_历史行业"] = out


# ============================================================
# Q4  市值能否从 volume/turn 推导
# ============================================================
def Q4_市值推导():
    bar("=")
    say("Q4  市值能不能从已有字段推导？（省掉额外下载）")
    say("    原理：turn(换手率%) = volume / 流通股本 × 100")
    say("         ⇒ 流通股本 = volume × 100 / turn")
    bar("=")
    out = {}
    if not os.path.exists(DB):
        say("  找不到数据库，跳过\n")
        return
    c = sqlite3.connect(DB)

    最新 = c.execute("SELECT MAX(date) FROM daily").fetchone()[0]
    rows = c.execute("""
        SELECT d.code, b.name, d.close, d.volume, d.turn
        FROM daily d JOIN stock_basic b ON b.code=d.code
        WHERE d.date=? AND d.turn>0 AND d.volume>0 AND d.close>0
        ORDER BY d.volume DESC LIMIT 12
    """, (最新,)).fetchall()

    say(f"  取 {最新} 成交量最大的 12 只，推算流通股本与流通市值：\n")
    say(f"  {'代码':<12}{'名称':<9}{'收盘':>9}{'推算流通股本(亿股)':>20}{'流通市值(亿)':>14}")
    样本 = []
    for code, name, close, vol, turn in rows:
        股本 = vol * 100.0 / turn
        市值 = close * 股本
        say(f"  {code:<12}{(name or '')[:6]:<9}{close:>9.2f}"
            f"{股本/1e8:>20.2f}{市值/1e8:>14.0f}")
        样本.append({"代码": code, "名称": name, "收盘": close,
                     "流通股本亿股": round(股本 / 1e8, 2),
                     "流通市值亿元": round(市值 / 1e8, 1)})
    out["样本"] = 样本
    say()

    # 覆盖率：有多少行能算出市值
    总, 可算 = c.execute("""
        SELECT COUNT(*), SUM(CASE WHEN turn>0 AND volume>0 AND close>0
                                  THEN 1 ELSE 0 END) FROM daily
    """).fetchone()
    say(f"  全库 {总:,} 行中，{可算:,} 行可推算市值"
        f"（{可算/max(总,1)*100:.1f}%）")
    out["总行数"] = 总
    out["可推算行数"] = 可算
    out["覆盖率"] = round(可算 / max(总, 1) * 100, 2)
    if 可算 / max(总, 1) > 0.95:
        say("  ✓ 覆盖率足够 → 『剔除最小30%市值』可以严格实现，无需额外下载")
        out["结论"] = "可用"
    else:
        say("  ○ 覆盖率偏低，停牌日 turn=0 属正常，回测时用最近一个有效值即可")
        out["结论"] = "基本可用，停牌日需前向填充"
    say()
    c.close()
    R["Q4_市值推导"] = out


# ============================================================
# Q5  并发压测
# ============================================================
def Q5_并发():
    bar("=")
    say("Q5  多进程并发能跑多快？会不会被限流？")
    bar("=")
    out = {}
    if not os.path.exists(DB):
        say("  找不到数据库，跳过\n")
        return

    import multiprocessing as mp
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import mp_fetch
    except Exception as e:
        say(f"  找不到 mp_fetch.py：{e}\n")
        return

    c = sqlite3.connect(DB)
    codes = [r[0] for r in c.execute(
        "SELECT code FROM stock_basic WHERE type='1' AND "
        "(out_date IS NULL OR TRIM(out_date)='') ORDER BY code").fetchall()]
    c.close()
    if len(codes) < 40:
        say("  股票太少，跳过\n")
        return

    # 取一批中间位置的股票做测试（避开已下载的抽样点）
    样本 = codes[len(codes)//3: len(codes)//3 + 32]

    for 进程数 in (1, 4, 8):
        批 = 样本[:8] if 进程数 == 1 else 样本[8:16] if 进程数 == 4 else 样本[16:24]
        任务 = [(x, "2010-01-01", "2026-09-14") for x in 批]
        say(f"  测试 {进程数} 进程 × {len(批)} 只 ...")
        t0 = time.time()
        成功 = 失败 = 0
        总根 = 0
        try:
            if 进程数 == 1:
                for a in 任务:
                    code, rows, fields, err, dt = mp_fetch.取日线(a)
                    if rows is None:
                        失败 += 1
                    else:
                        成功 += 1; 总根 += len(rows)
            else:
                with mp.Pool(processes=进程数,
                             initializer=mp_fetch.子进程登录) as pool:
                    for code, rows, fields, err, dt in pool.imap_unordered(
                            mp_fetch.取日线, 任务):
                        if rows is None:
                            失败 += 1
                        else:
                            成功 += 1; 总根 += len(rows)
        except Exception as e:
            say(f"    ✗ 并发本身出错：{type(e).__name__}: {e}")
            out[f"{进程数}进程"] = {"错误": f"{type(e).__name__}: {e}"}
            continue

        用时 = time.time() - t0
        每只 = 用时 / max(len(批), 1)
        全量小时 = 每只 * 5556 / 3600
        say(f"    用时 {用时:.0f}s   {每只:.1f}s/只   成功{成功} 失败{失败}"
            f"   → 全量约 {全量小时:.1f} 小时")
        out[f"{进程数}进程"] = {"用时秒": round(用时, 1), "每只秒": round(每只, 2),
                                "成功": 成功, "失败": 失败,
                                "全量预计小时": round(全量小时, 1)}

    # 选结论
    可用 = {k: v for k, v in out.items() if "每只秒" in v and v["失败"] == 0}
    if 可用:
        最佳 = min(可用, key=lambda k: 可用[k]["每只秒"])
        say()
        say(f"  ✓ 最快且零失败：{最佳}"
            f"（{可用[最佳]['每只秒']}s/只，全量约 {可用[最佳]['全量预计小时']} 小时）")
        out["建议"] = 最佳
    有失败 = [k for k, v in out.items() if v.get("失败", 0) > 0]
    if 有失败:
        say(f"  ⚠ 这些并发数出现失败，可能被限流：{有失败}")
        out["疑似限流"] = 有失败
    say()
    R["Q5_并发"] = out


# ============================================================
def main():
    say()
    bar("=")
    say("   A股选股工具 · 诊断")
    say("   把三个悬而未决的问题一次问清楚，不猜")
    bar("=")
    say()

    for 名, fn in [("Q1", Q1_财务异常), ("Q2", Q2_分红列名),
                   ("Q3", Q3_历史行业), ("Q4", Q4_市值推导),
                   ("Q5", Q5_并发)]:
        try:
            fn()
        except Exception as e:
            say(f"\n  {名} 出错（不影响其他项）：{type(e).__name__}: {e}\n")
            R[f"{名}_错误"] = f"{type(e).__name__}: {e}"

    p = os.path.join(OUT_DIR, "诊断结果.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUT_DIR, "诊断日志.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(日志))

    bar("=")
    say("诊断完成")
    bar("=")
    say(f"  {p}")
    say()
    say("  ▶ 把 output\\诊断结果.json 发回给 Claude")
    say()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say("\n出错了，请把下面内容发回给 Claude：\n")
        traceback.print_exc()
    input("\n按回车键关闭...")
