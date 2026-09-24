# -*- coding: utf-8 -*-
"""
A股选股工具 — 第三步：回测
================================
策略：质量红利低波（A股稳健配置）

执行口径（每一条都对应 A 股的真实约束）：
  · T+1        当日买入次日才能卖，日内止损不可执行
  · 涨跌停     涨停开盘买不到、跌停开盘卖不掉、一字板完全不可成交
  · 停牌       trade_status=0 当日不可交易
  · 整手       买入以 100 股为单位，用真实价（成交额/成交量）判断买得起
  · 成本       佣金万2.5(单笔最低5元) + 印花税0.05%(卖出) + 过户费0.001%(双边)
               + 滑点 0.1%(单边)
  · 估值       持仓收益用后复权价（含分红再投），整手用真实价

估值与真实价的区别很要紧：库里 close 是后复权价，不是真实价格。
后复权价只能用来算收益率；判断"一手多少钱"必须用 成交额/成交量。
"""

import os, sys, json, time, math, warnings, traceback
from datetime import datetime
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "output")
os.makedirs(OUT_DIR, exist_ok=True)

# ============================================================
# 配置 —— 全部来自 config.json（双击 05_控制台.bat 可以用界面改）
# 读不到配置文件也能跑：settings 会回退到验证过的默认值并给出提示。
# ============================================================
import settings as S

配置 = S.读配置()
E.应用配置(配置)

初始资金 = float(配置["资金与成本"]["初始资金"])
调仓频率 = 配置["调仓"]["调仓频率"]
回测起点 = 配置["回测"]["回测起点"]
样本外年数 = int(配置["回测"]["样本外年数"])
熔断阈值 = float(配置["调仓"]["熔断阈值"])
运气模拟次数 = int(配置["回测"]["运气模拟次数"])
配置警告 = list(S.警告)
# ============================================================

日志 = []


def say(m=""):
    print(m, flush=True)
    日志.append(str(m))


def bar(ch="-"):
    say(ch * 66)


def 用时(秒):
    秒 = int(秒)
    if 秒 < 60:
        return f"{秒}秒"
    if 秒 < 3600:
        return f"{秒//60}分{秒%60}秒"
    return f"{秒//3600}小时{(秒%3600)//60}分"


# ============================================================
# 单次回测
# ============================================================
def 跑一次(D, 调仓日列表, 资金, 熔断=None, 随机选股=None, 静默=False,
          记录明细=False):
    """
    熔断: None 或 0.20（组合回撤超过该值则降至半仓）
    随机选股: None 走正常排序；给 np.random.Generator 则从合格池随机取 N 只
              （用来量化「运气占比」）
    返回 dict：净值序列、调仓明细、统计
    """
    说 = (lambda *a, **k: None) if 静默 else say
    交易日 = D.交易日
    日期索引 = {d: i for i, d in enumerate(交易日)}

    现金 = float(资金)
    持仓 = {}          # code -> 等效后复权股数
    净值记录, 调仓记录 = [], []
    上期N = None
    峰值 = 资金
    降仓中 = False

    # 全市场 ROE 历史中位数（门槛的锚，用「截至上一个调仓日」的历史，不偷看未来）
    ROE历史 = []

    起 = 日期索引[调仓日列表[0]]
    for i in range(起, len(交易日)):
        今天 = 交易日[i]

        # ---------- 估值（后复权价，含分红再投） ----------
        持仓市值 = 0.0
        for code, 股数 in 持仓.items():
            p = D.收盘.iat[i, D.收盘.columns.get_loc(code)]
            if np.isfinite(p):
                持仓市值 += 股数 * p
            else:   # 停牌：沿用最近有效价
                last = D.收盘[code].iloc[:i + 1].last_valid_index()
                if last is not None:
                    持仓市值 += 股数 * D.收盘[code].loc[last]
        总资产 = 现金 + 持仓市值
        净值记录.append((今天, 总资产))
        峰值 = max(峰值, 总资产)
        回撤 = 总资产 / 峰值 - 1

        if 今天 not in 调仓日列表:
            continue

        # ---------- 熔断 ----------
        目标仓位 = 1.0
        if 熔断 is not None:
            if 回撤 <= -熔断:
                降仓中 = True
            elif 回撤 > -熔断 / 2:
                降仓中 = False
            if 降仓中:
                目标仓位 = 0.5

        # ---------- 因子与股票池 ----------
        F = E.截面因子(D, 今天)
        if not len(F):
            continue
        池, 池明细 = E.建股票池(F, D, 今天)
        if len(池) < 10:
            continue

        # ROE 门槛的锚：全市场历史中位数（只用已发生的）
        本期ROE中位 = float(np.nanmedian(F.loc[池, "roe_ttm"]))
        if np.isfinite(本期ROE中位):
            ROE历史.append(本期ROE中位)
        门槛ROE = float(np.median(ROE历史)) if ROE历史 else 8.0

        合格, 门槛明细 = E.合格标的(F, 池, D, 今天, 门槛ROE)
        综合分, 分组 = E.打分(F, 池)

        # ---------- 选股（先排序 → 再按买得起过滤 → N 由资金决定）----------
        选中, N, 被价格挡掉, 补足 = E.选股(F, 综合分, 合格, 总资产, 上期N)
        if len(选中) == 0:
            continue

        if 随机选股 is not None:
            # 运气模拟：在「买得起的合格标的」里随机取 N 只，而不是取分数最高的
            池全 = 合格 if len(合格) else 综合分.index
            一手 = F.loc[池全, "真实价"] * 100
            可买 = 池全[(一手 <= 总资产 / max(N, 1)).values]
            if len(可买) >= N:
                选中 = pd.Index(随机选股.choice(np.asarray(可买), size=N,
                                                replace=False))
        上期N = len(选中)

        权重 = E.定权重(F, 选中) * 目标仓位

        # ---------- 卖出 ----------
        卖出成本合计 = 0.0
        for code in list(持仓.keys()):
            if code in 权重.index:
                continue
            if not E.可卖(D, code, i):
                continue                      # 跌停/停牌/一字板卖不掉，留到下期
            j = D.收盘.columns.get_loc(code)
            p = D.收盘.iat[i, j]
            if not np.isfinite(p):
                continue
            金额 = 持仓[code] * p
            费 = E.卖出成本(金额)
            现金 += 金额 - 费
            卖出成本合计 += 费
            del 持仓[code]

        # ---------- 买入 / 调整 ----------
        总资产 = 现金 + sum(
            股数 * D.收盘.iat[i, D.收盘.columns.get_loc(c)]
            for c, 股数 in 持仓.items()
            if np.isfinite(D.收盘.iat[i, D.收盘.columns.get_loc(c)]))
        买入成本合计 = 0.0
        实际买入 = []

        for code, w in 权重.items():
            目标金额 = 总资产 * w
            已持 = 0.0
            if code in 持仓:
                p = D.收盘.iat[i, D.收盘.columns.get_loc(code)]
                已持 = 持仓[code] * p if np.isfinite(p) else 0.0
            差额 = 目标金额 - 已持
            if 差额 <= 0:
                continue
            if not E.可买(D, code, i):
                continue
            真价 = F.at[code, "真实价"]
            if not np.isfinite(真价) or 真价 <= 0:
                continue
            手数 = int(差额 // (真价 * 100))
            if 手数 < 1:
                continue
            金额 = 手数 * 100 * 真价
            费 = E.买入成本(金额)
            if 金额 + 费 > 现金:
                手数 = int((现金 * 0.995) // (真价 * 100))
                if 手数 < 1:
                    continue
                金额 = 手数 * 100 * 真价
                费 = E.买入成本(金额)
                if 金额 + 费 > 现金:
                    continue
            hfq = D.收盘.iat[i, D.收盘.columns.get_loc(code)]
            if not np.isfinite(hfq) or hfq <= 0:
                continue
            持仓[code] = 持仓.get(code, 0.0) + 金额 / hfq
            现金 -= 金额 + 费
            买入成本合计 += 费
            实际买入.append(code)

        rec = {
            "日期": 今天, "总资产": round(总资产, 2),
            "合格数": int(len(合格)), "目标持仓数": int(N),
            "实际持仓数": int(len(持仓)), "买入数": len(实际买入),
            "是否补足": bool(补足), "目标仓位": 目标仓位,
            "被价格挡掉": int(被价格挡掉),
            "回撤": round(float(回撤), 4),
            "买入成本": round(买入成本合计, 2),
            "卖出成本": round(卖出成本合计, 2),
        }
        if 记录明细:
            rec["门槛"] = 门槛明细
            rec["池"] = 池明细
            rec["持仓"] = [
                {"代码": c, "名称": str(D.名录["name"].get(c, "")),
                 "权重": round(float(权重.get(c, 0)), 4),
                 "真实价": round(float(F.at[c, "真实价"]), 2),
                 "一手金额": round(float(F.at[c, "真实价"]) * 100, 0),
                 "股息率%": round(float(F.at[c, "股息率"]) * 100, 2)
                            if np.isfinite(F.at[c, "股息率"]) else None,
                 "ROE%": round(float(F.at[c, "roe_ttm"]), 2)
                         if np.isfinite(F.at[c, "roe_ttm"]) else None,
                 "年化波动%": round(float(F.at[c, "波动率"]) * 100, 1),
                 "行业": str(F.at[c, "行业"]),
                 } for c in 权重.index]
        调仓记录.append(rec)

    nv = pd.Series(dict(净值记录)).astype(float)
    nv.index = pd.to_datetime(nv.index)
    return {"净值": nv, "调仓": 调仓记录}


# ============================================================
# 指标
# ============================================================
def 指标(nv, 基准=None):
    if len(nv) < 2:
        return {}
    年数 = (nv.index[-1] - nv.index[0]).days / 365.25
    总收益 = nv.iloc[-1] / nv.iloc[0] - 1
    年化 = (1 + 总收益) ** (1 / 年数) - 1 if 年数 > 0 else 0.0
    回撤序列 = nv / nv.cummax() - 1
    最大回撤 = float(回撤序列.min())
    日收益 = nv.pct_change().dropna()
    夏普 = (日收益.mean() / 日收益.std() * np.sqrt(252)) if 日收益.std() > 0 else 0.0
    月 = nv.resample("ME").last().pct_change().dropna()

    # 最差连续12个月
    滚12 = nv.resample("ME").last().pct_change(12).dropna()
    最差12 = float(滚12.min()) if len(滚12) else float("nan")

    m = {
        "起": str(nv.index[0].date()), "止": str(nv.index[-1].date()),
        "年数": round(年数, 2),
        "总收益": round(float(总收益), 4),
        "年化": round(float(年化), 4),
        "最大回撤": round(最大回撤, 4),
        "Calmar": round(float(年化 / abs(最大回撤)), 3) if 最大回撤 < 0 else None,
        "夏普": round(float(夏普), 3),
        "月胜率": round(float((月 > 0).mean()), 4) if len(月) else None,
        "最差连续12个月": round(最差12, 4),
    }
    # 分年度
    年末 = nv.resample("YE").last()
    年初 = nv.resample("YE").first()
    m["分年度"] = {str(d.year): round(float(年末.iloc[k] / 年初.iloc[k] - 1), 4)
                   for k, d in enumerate(年末.index)}

    if 基准 is not None and len(基准) > 1:
        b = 基准.reindex(nv.index).ffill()
        b = b / b.iloc[0]
        s = nv / nv.iloc[0]
        超额 = s.iloc[-1] / b.iloc[-1] - 1
        b年化 = (b.iloc[-1]) ** (1 / 年数) - 1 if 年数 > 0 else 0
        m["基准年化"] = round(float(b年化), 4)
        m["累计超额"] = round(float(超额), 4)
        m["基准最大回撤"] = round(float((b / b.cummax() - 1).min()), 4)
        # 滚动3年胜率
        s月 = s.resample("ME").last()
        b月 = b.resample("ME").last()
        r3 = (s月.pct_change(36) > b月.pct_change(36)).dropna()
        m["滚动3年跑赢基准比例"] = round(float(r3.mean()), 4) if len(r3) else None
    return m


def 取基准(D, code="sh.000300"):
    x = D.指数[D.指数["code"] == code].copy()
    if not len(x):
        return None
    x["date"] = pd.to_datetime(x["date"])
    return x.set_index("date")["close"].astype(float).sort_index()


# ============================================================
# 验收标准（开工前约定，不达标如实报告，不调参凑及格）
# ============================================================
def 核对验收(全程, 样本外, 基准指标):
    条 = []

    def 加(名, 达标, 实际, 要求):
        条.append({"项": 名, "达标": bool(达标),
                   "实际": 实际, "要求": 要求})

    年化 = 全程.get("年化")
    hs300 = 基准指标.get("沪深300年化")
    红利 = 基准指标.get("中证红利年化")
    # 价格指数不含股息，按 A 股平均股息率约 2% 折算成全收益口径
    hs300全 = (hs300 + 0.02) if hs300 is not None else None
    红利全 = (红利 + 0.04) if 红利 is not None else None

    加("年化跑赢沪深300全收益",
       年化 is not None and hs300全 is not None and 年化 > hs300全,
       f"{年化:.2%}" if 年化 is not None else "—",
       f">{hs300全:.2%}（价格指数{hs300:.2%}+估算股息2%）" if hs300全 else "—")
    加("年化跑赢中证红利全收益",
       年化 is not None and 红利全 is not None and 年化 > 红利全,
       f"{年化:.2%}" if 年化 is not None else "—",
       f">{红利全:.2%}（价格指数{红利:.2%}+估算股息4%）" if 红利全 else "—")

    mdd, bmdd = 全程.get("最大回撤"), 全程.get("基准最大回撤")
    加("最大回撤小于同期沪深300",
       mdd is not None and bmdd is not None and mdd > bmdd,
       f"{mdd:.2%}" if mdd is not None else "—",
       f"优于 {bmdd:.2%}" if bmdd is not None else "—")

    cal = 全程.get("Calmar")
    加("Calmar > 0.5", cal is not None and cal > 0.5,
       f"{cal}" if cal is not None else "—", "> 0.5")

    r3 = 全程.get("滚动3年跑赢基准比例")
    加("滚动3年跑赢沪深300比例 > 70%",
       r3 is not None and r3 > 0.70,
       f"{r3:.1%}" if r3 is not None else "—", "> 70%")

    内, 外 = 全程.get("年化"), 样本外.get("年化")
    加(f"样本外（最后{样本外年数}年）不显著劣于样本内",
       内 is not None and 外 is not None and 外 > 内 - 0.10,
       f"样本外 {外:.2%} vs 全程 {内:.2%}" if (内 is not None and 外 is not None) else "—",
       "样本外年化不低于全程 10 个百分点")

    w12 = 全程.get("最差连续12个月")
    条.append({"项": "最差连续12个月亏损（无门槛，但必须摆出来）",
               "达标": None,
               "实际": f"{w12:.2%}" if w12 == w12 else "—",
               "要求": "如实告知"})

    必过 = [x for x in 条 if x["达标"] is not None]
    return {"逐条": 条,
            "通过数": sum(1 for x in 必过 if x["达标"]),
            "总数": len(必过),
            "全部通过": all(x["达标"] for x in 必过)}


# ============================================================
# 主流程
# ============================================================
def main():
    t0 = time.time()
    say()
    bar("=")
    say("   A股选股工具 · 第三步：回测")
    say("   策略：质量红利低波（A股稳健配置）")
    bar("=")
    say()
    say(f"  初始资金 {初始资金:,.0f} 元    调仓频率 每{调仓频率}"
        f"    回测起点 {回测起点}")
    say(f"  单笔最小金额 {E.单笔最小金额:,.0f} 元"
        f"（0=不限）    持仓上限 {E.持仓上限} 只")
    say(f"  因子权重 " + "  ".join(f"{k}={float(v):g}" for k, v in E.因子权重.items()))
    say(f"  成本口径：佣金{E.佣金费率*10000:g}‱(最低{E.佣金最低:g}元) "
        f"+ 印花税{E.印花税率*100:g}%(卖出) "
        f"+ 过户费{E.过户费率*100:g}%(双边) + 滑点{E.滑点率*100:g}%(单边)")
    _e = S.成本预估(配置, 平均换手率=0.25)
    say(f"  成本预估（假设每期换手25%）：{_e['实际持仓数']} 只 × 每仓 "
        f"{_e['每仓金额']:,.0f} 元，单笔佣金占比 {_e['单笔佣金占比%']}%，"
        f"年成本约 {_e['年成本占比%']}%")
    say(f"    ↑ 这是按初始资金算的上限；账户变大后成本占比会下降")
    for _w in 配置警告:
        say(f"  ⚠ {_w}")
    say()

    bar()
    say("第 1 步  加载数据")
    bar()
    D = E.数据(起始="2010-01-01", 说=say)
    say()

    日历 = [d for d in E.调仓日历(D.交易日, 调仓频率) if d >= 回测起点]
    say(f"  调仓日 {len(日历)} 个：{日历[0]} ~ {日历[-1]}")
    say()

    结果 = {"配置": {"初始资金": 初始资金, "调仓频率": 调仓频率,
                     "回测起点": 回测起点, "样本外年数": 样本外年数,
                     "成本": {"佣金费率": E.佣金费率, "佣金最低": E.佣金最低,
                              "印花税": E.印花税率, "过户费": E.过户费率,
                              "滑点": E.滑点率}},
            "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # ---------- 基准 ----------
    基准 = {}
    for code, 名 in [("sh.000300", "沪深300"), ("sh.000922", "中证红利"),
                     ("sh.000905", "中证500")]:
        s = 取基准(D, code)
        if s is not None:
            基准[名] = s
    hs300 = 基准.get("沪深300")

    # ---------- 两条曲线：无熔断 vs 熔断 ----------
    bar()
    say("第 2 步  回测（两种风控口径并排跑，用数据说话）")
    bar()
    曲线 = {}
    for 名, 熔 in [("无熔断", None), (f"{int(熔断阈值*100)}%熔断", 熔断阈值)]:
        say(f"  跑「{名}」...")
        tt = time.time()
        r = 跑一次(D, 日历, 初始资金, 熔断=熔, 静默=True,
                  记录明细=(熔 is None))
        曲线[名] = r
        m = 指标(r["净值"], hs300)
        say(f"    年化 {m['年化']:.2%}   最大回撤 {m['最大回撤']:.2%}"
            f"   Calmar {m['Calmar']}   用时 {time.time()-tt:.0f}s")
    say()

    主 = 曲线["无熔断"]
    nv = 主["净值"]

    # ---------- 指标 ----------
    bar()
    say("第 3 步  指标与验收")
    bar()
    全程 = 指标(nv, hs300)
    切 = nv.index[-1] - pd.DateOffset(years=样本外年数)
    样本外 = 指标(nv[nv.index >= 切], hs300)

    基准指标 = {}
    for 名, s in 基准.items():
        b = s.reindex(nv.index).ffill().dropna()
        if len(b) > 1:
            年 = (b.index[-1] - b.index[0]).days / 365.25
            基准指标[f"{名}年化"] = round(
                float((b.iloc[-1] / b.iloc[0]) ** (1 / 年) - 1), 4)

    验收 = 核对验收(全程, 样本外, 基准指标)

    for k in ("年化", "最大回撤", "Calmar", "夏普", "月胜率",
              "最差连续12个月", "滚动3年跑赢基准比例"):
        v = 全程.get(k)
        if v is None:
            continue
        say(f"  {k:<16} {v:.2%}" if isinstance(v, float) and abs(v) < 10
            else f"  {k:<16} {v}")
    say()
    say(f"  验收：{验收['通过数']}/{验收['总数']} 条达标")
    for x in 验收["逐条"]:
        标 = "✓" if x["达标"] else ("—" if x["达标"] is None else "✗")
        say(f"    {标} {x['项']}")
        say(f"       实际 {x['实际']}   要求 {x['要求']}")
    say()

    # ---------- 运气占比 ----------
    bar()
    say(f"第 4 步  运气占比（随机选股重跑 {运气模拟次数} 次）")
    say("        小资金只能持几只，结果里有多大一块是运气，必须量化")
    bar()
    say(f"        注意：这一步要把整个回测重跑 {运气模拟次数} 次，是全程最慢的一步。")
    say(f"        想快速试参数，可以在控制台把「运气模拟次数」调到 10～15；")
    say(f"        定稿验证时再用 40 次。")
    say()
    rng_年化 = []
    _t运气 = time.time()
    for k in range(运气模拟次数):
        rng = np.random.default_rng(1000 + k)
        r = 跑一次(D, 日历, 初始资金, 熔断=None, 随机选股=rng, 静默=True)
        m = 指标(r["净值"])
        if m.get("年化") is not None:
            rng_年化.append(m["年化"])
        用 = time.time() - _t运气
        剩 = 用 / (k + 1) * (运气模拟次数 - k - 1)
        say(f"  已完成 {k+1}/{运气模拟次数}   单次 {用/(k+1):.0f}s   "
            f"已用 {用时(用)}   剩约 {用时(剩)}")
    if rng_年化:
        a = np.array(rng_年化)
        分布 = {"5%": float(np.percentile(a, 5)),
                "25%": float(np.percentile(a, 25)),
                "50%": float(np.percentile(a, 50)),
                "75%": float(np.percentile(a, 75)),
                "95%": float(np.percentile(a, 95))}
        say()
        say("  同样规则、随机选股的年化分布：")
        say("    " + "   ".join(f"{k}={v:.2%}" for k, v in 分布.items()))
        say(f"  按分数选股的实际年化：{全程['年化']:.2%}")
        位置 = float((a < 全程["年化"]).mean())
        say(f"  实际结果位于随机分布的 {位置:.0%} 分位")
        if 位置 < 0.80:
            say("  ⚠ 排序带来的优势不明显——大部分结果由运气决定，")
            say("    这正是小资金、少持仓的代价，不是模型坏了。")
        结果["运气分布"] = {"分布": 分布, "实际分位": 位置,
                            "样本数": len(rng_年化)}
    say()

    # ---------- 落盘 ----------
    结果.update({
        "全程": 全程, "样本外": 样本外, "基准": 基准指标, "验收": 验收,
        "熔断对比": {名: 指标(r["净值"], hs300) for 名, r in 曲线.items()},
        "调仓记录": 主["调仓"],
    })
    净值表 = pd.DataFrame({"策略": nv})
    for 名, s in 基准.items():
        净值表[名] = s.reindex(nv.index).ffill()
    净值表.to_csv(os.path.join(OUT_DIR, "净值曲线.csv"),
                  encoding="utf-8-sig")
    with open(os.path.join(OUT_DIR, "回测结果.json"), "w",
              encoding="utf-8") as f:
        json.dump(结果, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUT_DIR, "回测日志.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(日志))

    try:
        import report
        p = report.生成(结果, 净值表, OUT_DIR)
        say(f"  报告：{p}")
        try:
            os.startfile(p)
        except Exception:
            pass
    except Exception as e:
        say(f"  （HTML 报告生成失败，数据已存 json：{type(e).__name__}: {e}）")

    bar("=")
    say(f"回测完成，用时 {time.time()-t0:.0f} 秒")
    bar("=")
    say(f"  output\\回测结果.json")
    say(f"  output\\净值曲线.csv")
    say()
    say("  ▶ 把 output\\回测结果.json 发回给 Claude")
    say()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say("\n出错了，请把下面内容发回给 Claude：\n")
        traceback.print_exc()
        try:
            with open(os.path.join(OUT_DIR, "回测日志.txt"), "w",
                      encoding="utf-8") as f:
                f.write("\n".join(日志) + "\n\n" + traceback.format_exc())
        except Exception:
            pass
    if not os.environ.get("XUANGU_NO_PAUSE"):
        input("\n按回车键关闭...")