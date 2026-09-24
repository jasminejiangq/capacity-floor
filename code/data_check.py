# -*- coding: utf-8 -*-
"""
A股选股工具 — 第一步：数据体检
========================================
这个脚本不选股、不交易、不下载大量数据。
它只回答一个问题：这台电脑上，我们需要的数据到底拿不拿得到。

输出:
  output/数据体检报告.html   给你看的
  output/数据体检结果.json   给 Claude 看的

作者: Claude  |  版本: 1.0
"""

import sys, os, json, time, platform, traceback, warnings
from datetime import datetime, date

warnings.filterwarnings("ignore")

# ============================================================
# 配置 —— 你可以改这里
# ============================================================
我的资金 = 2500        # 元。用来测算你能买几只股票
# ============================================================

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "output")
os.makedirs(OUT_DIR, exist_ok=True)

R = {
    "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "环境": {},
    "测试": [],
    "测算": {},
}


def say(msg=""):
    print(msg, flush=True)


def bar():
    say("-" * 62)


class Test:
    """每一项测试：失败不中断，记录下来继续。"""

    def __init__(self, 编号, 名称, 为什么重要, 必需=True):
        self.d = {
            "编号": 编号, "名称": 名称, "为什么重要": 为什么重要,
            "必需": 必需, "通过": False, "耗时秒": None,
            "说明": "", "样本": None, "错误": None,
        }
        self.t0 = None

    def __enter__(self):
        say(f"[{self.d['编号']}] {self.d['名称']} ... ")
        self.t0 = time.time()
        return self

    def ok(self, 说明, 样本=None):
        self.d["通过"] = True
        self.d["说明"] = 说明
        if 样本 is not None:
            self.d["样本"] = 样本

    def fail(self, 说明):
        self.d["通过"] = False
        self.d["说明"] = 说明

    def __exit__(self, et, ev, tb):
        self.d["耗时秒"] = round(time.time() - self.t0, 2)
        if et is not None:
            self.d["通过"] = False
            self.d["错误"] = f"{et.__name__}: {ev}"
            if not self.d["说明"]:
                self.d["说明"] = "调用报错，详见错误信息"
        mark = "  ✓ 通过" if self.d["通过"] else ("  ✗ 失败" if self.d["必需"] else "  ○ 不可用(非必需)")
        say(f"{mark}  [{self.d['耗时秒']}s]  {self.d['说明']}")
        if self.d["错误"]:
            say(f"       错误: {self.d['错误'][:220]}")
        say()
        R["测试"].append(self.d)
        return True      # 吞掉异常，继续下一项


def df_sample(df, n=3, cols=None):
    """把 DataFrame 的前几行转成可 JSON 化的样本"""
    try:
        d = df if cols is None else df[[c for c in cols if c in df.columns]]
        return {
            "行数": int(len(df)),
            "列名": [str(c) for c in df.columns][:40],
            "前几行": json.loads(d.head(n).to_json(orient="records", force_ascii=False)),
        }
    except Exception as e:
        return {"样本提取失败": str(e)}


# ============================================================
# 0. 环境
# ============================================================
def 检查环境():
    bar()
    say("第 0 步：检查运行环境")
    bar()
    R["环境"] = {
        "python版本": sys.version.split()[0],
        "位数": platform.architecture()[0],
        "系统": f"{platform.system()} {platform.release()}",
        "工作目录": ROOT,
    }
    for k, v in R["环境"].items():
        say(f"  {k}: {v}")

    v = sys.version_info
    if v < (3, 9):
        say("\n  ⚠ Python 版本过低（需要 3.9 以上）。请升级后重试。")
        R["环境"]["版本告警"] = "低于3.9"
    elif v >= (3, 13):
        say("\n  ⚠ Python 3.13+ 有些依赖包可能还没有预编译版本，")
        say("    如果下面安装失败，建议装一个 3.11 或 3.12。")
        R["环境"]["版本告警"] = "3.13+可能有兼容问题"
    say()


def 检查依赖():
    需要 = ["pandas", "numpy", "akshare", "baostock", "requests"]
    缺失 = []
    for m in 需要:
        try:
            __import__(m)
            say(f"  ✓ {m}")
        except Exception:
            say(f"  ✗ {m}  （未安装）")
            缺失.append(m)
    R["环境"]["缺失依赖"] = 缺失
    say()
    return 缺失


# ============================================================
# 1. AKShare 测试
# ============================================================
def 测试_akshare():
    bar()
    say("第 1 组：AKShare —— 覆盖最广的免费数据源")
    bar()

    try:
        import akshare as ak
        import pandas as pd
    except Exception as e:
        say(f"  AKShare 无法导入，跳过整组测试：{e}\n")
        R["环境"]["akshare版本"] = None
        return None

    R["环境"]["akshare版本"] = getattr(ak, "__version__", "未知")
    say(f"  AKShare 版本: {R['环境']['akshare版本']}\n")

    快照 = None

    # --- 1.1 全市场快照（最关键的一个，后面很多测算靠它）---
    with Test("1.1", "全市场股票快照（代码/名称/最新价/市值）",
              "决定股票池，也用来算你的资金能买几只") as t:
        df = ak.stock_zh_a_spot_em()
        if df is None or len(df) == 0:
            t.fail("返回空表")
        else:
            快照 = df
            t.ok(f"拿到 {len(df)} 只股票", df_sample(df, 3))

    # --- 1.2 历史行情（后复权）---
    with Test("1.2", "个股历史日线（后复权）",
              "回测的地基。必须是后复权，前复权会引入未来信息") as t:
        df = ak.stock_zh_a_hist(symbol="600036", period="daily",
                                start_date="20100101", end_date="20260101",
                                adjust="hfq")
        if df is None or len(df) == 0:
            t.fail("返回空表")
        else:
            首 = str(df.iloc[0, 0]); 末 = str(df.iloc[-1, 0])
            t.ok(f"{len(df)} 根K线，{首} 至 {末}", df_sample(df, 2))

    # --- 1.3 业绩报表（横截面 + 公告日期）← 全场最重要 ---
    with Test("1.3", "业绩报表 · 按报告期一次拉全市场",
              "★最关键★ 若含『最新公告日期』，就能做到无前视偏差的财报对齐；"
              "且横截面拉取比逐股拉快三个数量级") as t:
        df = ak.stock_yjbb_em(date="20241231")
        if df is None or len(df) == 0:
            t.fail("返回空表")
        else:
            cols = [str(c) for c in df.columns]
            有公告日 = [c for c in cols if ("公告" in c and "日" in c)]
            if 有公告日:
                t.ok(f"{len(df)} 条，含公告日期字段：{有公告日}  → PIT 可实现",
                     df_sample(df, 2))
            else:
                t.fail(f"{len(df)} 条，但没找到公告日期字段。列名：{cols[:25]}")
                t.d["样本"] = df_sample(df, 2)

    # --- 1.4 分红数据 ---
    with Test("1.4", "分红送配 · 按报告期拉全市场",
              "红利因子的原料。没有它，策略的『红利』那一支就断了") as t:
        df = ak.stock_fhps_em(date="20241231")
        if df is None or len(df) == 0:
            t.fail("返回空表")
        else:
            t.ok(f"{len(df)} 条", df_sample(df, 2))

    # --- 1.5 行业分类 ---
    with Test("1.5", "行业分类", "行业中性化 + 单行业上限30% 都要用") as t:
        df = ak.stock_board_industry_name_em()
        if df is None or len(df) == 0:
            t.fail("返回空表")
        else:
            t.ok(f"{len(df)} 个行业板块", df_sample(df, 3))

    # --- 1.6 指数行情（基准）---
    with Test("1.6", "指数历史行情（沪深300）", "回测基准，验收标准要跟它比") as t:
        df = ak.index_zh_a_hist(symbol="000300", period="daily",
                                start_date="20100101", end_date="20260101")
        if df is None or len(df) == 0:
            t.fail("返回空表")
        else:
            t.ok(f"{len(df)} 根K线", df_sample(df, 2))

    # --- 1.7 退市股票（幸存者偏差）---
    with Test("1.7", "退市股票名单",
              "不含退市股的回测会系统性虚高。2026年内已有22家退市", 必需=False) as t:
        got = None
        for fn in ["stock_info_sh_delist", "stock_info_sz_delist"]:
            if hasattr(ak, fn):
                try:
                    d = getattr(ak, fn)()
                    if d is not None and len(d) > 0:
                        got = (fn, d); break
                except Exception:
                    continue
        if got:
            t.ok(f"{got[0]} 可用，{len(got[1])} 条", df_sample(got[1], 3))
        else:
            t.fail("未找到可用的退市名单接口（后面用 baostock 的 outDate 兜底）")

    # --- 1.8 无风险利率 ---
    with Test("1.8", "10年期国债收益率",
              "股息率门槛锚在它上面（高于无风险利率才算真红利）", 必需=False) as t:
        df = ak.bond_zh_us_rate(start_date="20240101")
        if df is None or len(df) == 0:
            t.fail("返回空表")
        else:
            cn10 = [c for c in df.columns if "中国" in str(c) and "10" in str(c)]
            t.ok(f"{len(df)} 条，中国10年期字段：{cn10}", df_sample(df, 2))

    return 快照


# ============================================================
# 2. Baostock 测试
# ============================================================
def 测试_baostock():
    bar()
    say("第 2 组：Baostock —— A股专用，数据规整，作为交叉验证与备份")
    bar()

    try:
        import baostock as bs
        import pandas as pd
    except Exception as e:
        say(f"  Baostock 无法导入，跳过整组测试：{e}\n")
        return

    with Test("2.0", "登录 Baostock", "后续所有 baostock 调用的前提") as t:
        lg = bs.login()
        if lg.error_code != "0":
            t.fail(f"登录失败 code={lg.error_code} msg={lg.error_msg}")
            return
        t.ok("登录成功")

    def rs_to_df(rs):
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        import pandas as pd
        return pd.DataFrame(rows, columns=rs.fields)

    # --- 2.1 股票基本信息（含上市/退市日期）---
    with Test("2.1", "股票基本信息（含上市日、退市日）",
              "用来剔除次新股，以及识别已退市股票（对抗幸存者偏差）") as t:
        df = rs_to_df(bs.query_stock_basic(code="sh.600036"))
        if len(df) == 0:
            t.fail("返回空表")
        else:
            t.ok(f"字段：{list(df.columns)}", df_sample(df, 1))

    # --- 2.2 季频盈利能力（含 pubDate）← 关键 ---
    with Test("2.2", "季频盈利能力（是否含 pubDate 公告日）",
              "★关键★ 与 1.3 互为备份。pubDate 是无前视偏差的前提") as t:
        df = rs_to_df(bs.query_profit_data(code="sh.600036", year=2024, quarter=4))
        if len(df) == 0:
            t.fail("返回空表")
        else:
            cols = list(df.columns)
            if "pubDate" in cols:
                t.ok(f"含 pubDate ✓  字段：{cols}", df_sample(df, 1))
            else:
                t.fail(f"未找到 pubDate。字段：{cols}")
                t.d["样本"] = df_sample(df, 1)

    # --- 2.3 逐股调用速度（决定建库策略）---
    with Test("2.3", "逐股调用速度实测",
              "如果逐股拉财务，5400只×76季≈41万次调用。这里测单次耗时来外推") as t:
        codes = ["sh.600036", "sz.000001", "sh.601318", "sz.000002", "sh.600519"]
        t0 = time.time()
        n = 0
        for c in codes:
            d = rs_to_df(bs.query_profit_data(code=c, year=2024, quarter=4))
            if len(d) > 0:
                n += 1
        每次 = (time.time() - t0) / max(len(codes), 1)
        总小时 = 每次 * 5400 * 76 / 3600
        R["测算"]["baostock逐股单次秒"] = round(每次, 3)
        R["测算"]["逐股拉财务预计小时"] = round(总小时, 1)
        t.ok(f"平均 {每次:.3f} 秒/次 → 逐股拉全部财务约需 {总小时:.1f} 小时"
             f"（所以必须用横截面拉取，见 1.3）")

    # --- 2.4 行情（后复权）---
    with Test("2.4", "历史K线（后复权，adjustflag=1）", "与 AKShare 交叉验证复权口径") as t:
        rs = bs.query_history_k_data_plus(
            "sh.600036", "date,code,open,high,low,close,volume,amount,turn,tradestatus,pctChg,isST",
            start_date="2024-01-01", end_date="2024-03-01",
            frequency="d", adjustflag="1")
        df = rs_to_df(rs)
        if len(df) == 0:
            t.fail("返回空表")
        else:
            有ST = "isST" in df.columns
            t.ok(f"{len(df)} 根K线，含 isST 标识：{有ST}，含停牌标识 tradestatus",
                 df_sample(df, 2))

    # --- 2.5 申万行业 ---
    with Test("2.5", "申万行业分类", "行业中性化的标准口径", 必需=False) as t:
        df = rs_to_df(bs.query_stock_industry())
        if len(df) == 0:
            t.fail("返回空表")
        else:
            t.ok(f"{len(df)} 条", df_sample(df, 3))

    # --- 2.6 全市场股票列表（某一天，用于构建历史股票池）---
    with Test("2.6", "指定日期的全市场股票列表",
              "★重要★ 能按历史日期取当时的股票列表 = 天然对抗幸存者偏差") as t:
        df = rs_to_df(bs.query_all_stock(day="2018-06-15"))
        if len(df) == 0:
            t.fail("返回空表")
        else:
            t.ok(f"2018-06-15 当天有 {len(df)} 只标的（含指数）", df_sample(df, 3))

    try:
        bs.logout()
    except Exception:
        pass


# ============================================================
# 3. 针对你资金的测算
# ============================================================
def 测算资金(快照):
    bar()
    say(f"第 3 步：按你的资金（{我的资金} 元）测算")
    bar()

    if 快照 is None or len(快照) == 0:
        say("  快照数据没拿到，跳过测算。\n")
        R["测算"]["状态"] = "无快照数据"
        return

    try:
        import pandas as pd, numpy as np
        df = 快照.copy()

        价列 = next((c for c in df.columns if str(c) in ("最新价", "现价")), None)
        名列 = next((c for c in df.columns if "名称" in str(c)), None)
        if 价列 is None:
            say("  找不到价格列，跳过测算。\n")
            R["测算"]["状态"] = "无价格列"
            return

        df["_价"] = pd.to_numeric(df[价列], errors="coerce")
        df = df[df["_价"] > 0]

        # 粗略剔除 ST / 退市整理（只为测算，不是正式股票池）
        if 名列 is not None:
            名 = df[名列].astype(str)
            df = df[~名.str.contains("ST", case=False, na=False)]
            df = df[~名.str.contains("退", na=False)]

        df["_一手"] = df["_价"] * 100
        q = df["_价"].quantile([.05, .1, .25, .5, .75, .9]).round(2).to_dict()
        分布 = {f"{int(k*100)}分位": float(v) for k, v in q.items()}

        R["测算"]["有效股票数"] = int(len(df))
        R["测算"]["股价分布"] = 分布
        R["测算"]["一手中位金额"] = float(round(df["_一手"].median(), 0))

        say(f"  剔除ST后共 {len(df)} 只股票")
        say(f"  股价分位: " + "  ".join(f"{k}={v}" for k, v in 分布.items()))
        say(f"  一手金额中位数: {R['测算']['一手中位金额']:.0f} 元")
        say()

        # 核心问题：以你的钱，目标持 N 只时，有多少只买得起？
        say(f"  以 {我的资金} 元，若目标持有 N 只，每只预算 = {我的资金}/N：")
        say()
        say("    N    每只预算    买得起的股票数    占比")
        表 = []
        for N in [2, 3, 4, 5, 6, 8, 10]:
            预算 = 我的资金 / N
            可买 = int((df["_一手"] <= 预算).sum())
            占比 = 可买 / len(df) * 100
            表.append({"N": N, "每只预算": round(预算, 0),
                       "可买只数": 可买, "占比%": round(占比, 1)})
            say(f"   {N:>2}    {预算:>7.0f}    {可买:>10}      {占比:>5.1f}%")
        R["测算"]["资金可行性"] = 表
        say()

        # 最便宜的能买的那些长什么样（防止滑向绩差股的第一手观察）
        if 名列 is not None:
            便宜 = df.nsmallest(15, "_一手")[[名列, "_价", "_一手"]]
            便宜.columns = ["名称", "价格", "一手金额"]
            R["测算"]["最低价15只"] = json.loads(
                便宜.to_json(orient="records", force_ascii=False))
            say("  （最低价的15只，仅供观察——注意低价不等于便宜，")
            say("    正式策略里价格只做可行性过滤，不做选股因子）")
            say("    " + "、".join(str(x) for x in 便宜["名称"].head(8).tolist()))
        say()
    except Exception as e:
        say(f"  测算出错: {e}")
        R["测算"]["错误"] = str(e)
        say()


# ============================================================
# 4. 报告
# ============================================================
HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>数据体检报告</title><style>
:root{--pp:#F6F7F9;--sf:#fff;--ink:#171B22;--i2:#434B59;--i3:#6C7585;
--rl:#DCE0E7;--ac:#2C3E63;--ok:#0F6E58;--no:#C2392F;--wn:#8A6008;--wb:#FBF3DF}
@media(prefers-color-scheme:dark){:root{--pp:#0F1218;--sf:#171B23;--ink:#E6E9EF;
--i2:#B3BBC9;--i3:#818B9C;--rl:#2A3140;--ac:#8FA8D8;--ok:#3FB394;--no:#E8695C;
--wn:#D9AC4A;--wb:#2A2314}}
*{box-sizing:border-box}body{margin:0;background:var(--pp);color:var(--ink);
font:15px/1.8 "Noto Sans SC",-apple-system,"Microsoft YaHei",sans-serif}
.w{max-width:900px;margin:0 auto;padding:0 20px 80px}
header{border-bottom:2px solid var(--ink);padding:40px 0 16px;margin-bottom:8px}
h1{font-size:30px;margin:0 0 8px;font-weight:700;letter-spacing:-.01em}
.sub{color:var(--i3);font-size:13px;font-family:ui-monospace,Consolas,monospace}
h2{font-size:20px;margin:44px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--ink)}
.verdict{padding:20px 22px;border-radius:3px;margin:24px 0;border:1px solid var(--rl);
border-left:4px solid var(--ac);background:var(--sf)}
.verdict.good{border-left-color:var(--ok)}.verdict.bad{border-left-color:var(--no)}
.verdict h3{margin:0 0 8px;font-size:17px}.verdict p{margin:0;color:var(--i2);font-size:14px}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:2px 24px;
margin:16px 0;padding:16px 0;border-top:1px solid var(--rl);border-bottom:1px solid var(--rl)}
.kv div{font-size:13px;color:var(--i3)}.kv b{display:block;font-size:10.5px;letter-spacing:.1em;
text-transform:uppercase;color:var(--i3);font-weight:500}.kv span{color:var(--ink);font-weight:600}
.t{border:1px solid var(--rl);border-radius:3px;background:var(--sf);margin:18px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:13.5px}
th,td{padding:10px 13px;text-align:left;border-bottom:1px solid var(--rl);vertical-align:top}
th{background:rgba(128,128,128,.07);font-size:11.5px;letter-spacing:.05em;white-space:nowrap}
tr:last-child td{border-bottom:0}
td.n{font-family:ui-monospace,Consolas,monospace;text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
.p{display:inline-block;font-family:ui-monospace,Consolas,monospace;font-size:10.5px;
font-weight:600;padding:2px 8px;border-radius:2px;white-space:nowrap}
.p.y{background:rgba(15,110,88,.13);color:var(--ok)}
.p.n{background:rgba(194,57,47,.13);color:var(--no)}
.p.o{background:rgba(138,96,8,.16);color:var(--wn)}
.why{color:var(--i3);font-size:12.5px;line-height:1.65;margin-top:3px}
.err{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:var(--no);
margin-top:5px;word-break:break-all}
.note{background:var(--wb);border-left:3px solid var(--wn);padding:15px 18px;
margin:20px 0;font-size:14px;border-radius:2px}
footer{margin-top:60px;padding-top:18px;border-top:2px solid var(--ink);
font-size:12.5px;color:var(--i3)}
</style></head><body><div class="w">
<header><h1>数据体检报告</h1>
<div class="sub">A股选股工具 · 第一步 · 生成于 __TIME__</div></header>
__BODY__
<footer>本报告由体检脚本自动生成，只反映本机当次运行结果。<br>
把 output 文件夹里的 <b>数据体检结果.json</b> 发回给 Claude，就能进行下一步。</footer>
</div></body></html>"""


def 写报告():
    必需项 = [t for t in R["测试"] if t["必需"]]
    通过数 = sum(1 for t in 必需项 if t["通过"])
    全过 = 通过数 == len(必需项) and len(必需项) > 0
    pit = any(t["通过"] for t in R["测试"] if t["编号"] in ("1.3", "2.2"))

    b = []

    # 结论
    if 全过 and pit:
        b.append('<div class="verdict good"><h3>✓ 可以进入下一步</h3>'
                 f'<p>{len(必需项)} 项必需数据全部拿得到，财报公告日期字段也在。'
                 '零预算方案成立，可以开始建本地数据库。</p></div>')
    elif pit:
        缺 = "、".join(t["名称"] for t in 必需项 if not t["通过"])
        b.append('<div class="verdict"><h3>○ 基本可行，但有缺口</h3>'
                 f'<p>关键的财报公告日期拿得到，但这几项失败了：<b>{缺}</b>。'
                 '把本报告发回给 Claude，会针对性地换接口或写兜底方案。</p></div>')
    else:
        b.append('<div class="verdict bad"><h3>✗ 需要先解决数据问题</h3>'
                 '<p>没能拿到带公告日期的财报数据。没有它，回测会有前视偏差，'
                 '跑出来的收益是假的。把本报告发回给 Claude 换方案。</p></div>')

    # 环境
    b.append("<h2>运行环境</h2><div class='kv'>")
    for k, v in R["环境"].items():
        if k == "缺失依赖":
            v = "无" if not v else "、".join(v)
        b.append(f"<div><b>{k}</b><span>{v}</span></div>")
    b.append("</div>")

    # 测试明细
    b.append("<h2>数据源测试明细</h2><div class='t'><table>"
             "<thead><tr><th>项目</th><th>结果</th><th>耗时</th><th>说明</th></tr></thead><tbody>")
    for t in R["测试"]:
        if t["通过"]:
            pill = '<span class="p y">通过</span>'
        elif t["必需"]:
            pill = '<span class="p n">失败</span>'
        else:
            pill = '<span class="p o">不可用</span>'
        err = f'<div class="err">{t["错误"]}</div>' if t["错误"] else ""
        b.append(f'<tr><td><b>{t["编号"]}　{t["名称"]}</b>'
                 f'<div class="why">{t["为什么重要"]}</div></td>'
                 f'<td>{pill}</td><td class="n">{t["耗时秒"]}s</td>'
                 f'<td>{t["说明"]}{err}</td></tr>')
    b.append("</tbody></table></div>")

    # 资金测算
    m = R.get("测算", {})
    if m.get("资金可行性"):
        b.append(f"<h2>你的资金能买几只（{我的资金} 元）</h2>")
        b.append("<div class='kv'>"
                 f"<div><b>有效股票数</b><span>{m.get('有效股票数','—')}</span></div>"
                 f"<div><b>一手金额中位数</b><span>{m.get('一手中位金额','—')} 元</span></div>"
                 "</div>")
        b.append("<div class='t'><table><thead><tr><th>目标持仓数</th>"
                 "<th>每只预算</th><th>买得起的股票数</th><th>占全市场</th>"
                 "</tr></thead><tbody>")
        for r in m["资金可行性"]:
            b.append(f'<tr><td class="n">{r["N"]}</td>'
                     f'<td class="n">{r["每只预算"]:.0f} 元</td>'
                     f'<td class="n">{r["可买只数"]}</td>'
                     f'<td class="n">{r["占比%"]}%</td></tr>')
        b.append("</tbody></table></div>")
        b.append('<div class="note">这张表决定了策略的形态。'
                 '可买只数越多，说明整手约束对你越不构成问题；'
                 '如果某一行的占比很低，说明按那个持仓数会被迫只能选低价股，'
                 '而低价不等于便宜——正式策略里价格只做可行性过滤，绝不做选股因子。</div>')

    if m.get("逐股拉财务预计小时"):
        b.append("<h2>建库策略验证</h2>")
        b.append(f'<div class="note">逐股拉财务实测 <b>{m["baostock逐股单次秒"]} 秒/次</b>，'
                 f'全市场推算需要 <b>{m["逐股拉财务预计小时"]} 小时</b>。<br>'
                 '这就是为什么必须按报告期横截面拉取（测试 1.3）——同样的数据，'
                 '几分钟就能拿完。</div>')

    html = HTML.replace("__TIME__", R["生成时间"]).replace("__BODY__", "\n".join(b))

    p1 = os.path.join(OUT_DIR, "数据体检报告.html")
    p2 = os.path.join(OUT_DIR, "数据体检结果.json")
    with open(p1, "w", encoding="utf-8") as f:
        f.write(html)
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2, default=str)
    return p1, p2, 全过, pit


# ============================================================
def main():
    say()
    say("=" * 62)
    say("   A股选股工具 · 第一步：数据体检")
    say("   这一步不选股、不交易，只检查数据拿不拿得到")
    say("=" * 62)
    say()

    检查环境()

    bar(); say("检查依赖包"); bar()
    缺失 = 检查依赖()
    if "akshare" in 缺失 and "baostock" in 缺失:
        say("  ✗ 两个数据源包都没装上，无法继续。")
        say("    请把这个窗口的内容截图发回给 Claude。")
        say()
        input("按回车键关闭...")
        return

    快照 = 测试_akshare()
    测试_baostock()
    测算资金(快照)

    p1, p2, 全过, pit = 写报告()

    bar()
    say("体检完成")
    bar()
    必需 = [t for t in R["测试"] if t["必需"]]
    say(f"  必需项通过: {sum(1 for t in 必需 if t['通过'])} / {len(必需)}")
    say(f"  财报公告日期(PIT): {'拿得到 ✓' if pit else '没拿到 ✗ —— 这是硬伤，要换方案'}")
    say()
    say("  报告已生成：")
    say(f"    {p1}")
    say(f"    {p2}")
    say()
    say("  ▶ 下一步：把 output 文件夹里的")
    say("    「数据体检结果.json」发回给 Claude，就能继续。")
    say()
    try:
        os.startfile(p1)      # Windows 自动打开报告
    except Exception:
        pass
    input("按回车键关闭...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\n已取消。")
    except Exception:
        say("\n脚本出现意外错误，请把下面全部内容发回给 Claude：\n")
        traceback.print_exc()
        input("\n按回车键关闭...")
