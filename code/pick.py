# -*- coding: utf-8 -*-
"""
今日选股
========
用 config.json 里的参数，在最新一个交易日跑一遍完整的选股流程，
输出候选清单 + 完整的筛选漏斗 + 每只股票的因子拆解 + 真实下单成本测算。

这不是「推荐买入」，是「按你设定的规则，今天符合条件的是这些」。
买不买、买哪只，由你决定。

刻意做到的几件事：
  · 漏斗每一步剩多少只都摆出来，不做黑箱
  · 每只股票的 ROE / 股息率 / 波动率 / 估值 分别是多少、排第几，全列出来
  · 按你的资金算出真实下单金额、佣金、总成本、以及要涨多少才回本
  · 明确标注策略的回测表现，包括它没达标的那几项
"""
import os, sys, json, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
import settings as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

日志 = []


def say(m=""):
    print(m, flush=True)
    日志.append(str(m))


def bar(ch="-"):
    say(ch * 66)


def 主():
    t0 = time.time()
    配置 = S.读配置()
    E.应用配置(配置)
    资金 = float(配置["资金与成本"]["初始资金"])

    bar("=")
    say("   今日选股 · 按你在 config.json 里设定的规则")
    bar("=")
    for w in S.警告:
        say(f"  ⚠ {w}")
    say(f"  资金 {资金:,.0f} 元   单笔最小 {E.单笔最小金额:,.0f} 元   "
        f"持仓上限 {E.持仓上限} 只")
    say(f"  因子权重 " + "  ".join(f"{k}={float(v):g}" for k, v in E.因子权重.items()))
    say()

    D = E.数据(起始="2010-01-01", 说=say)
    今天 = D.交易日[-1]
    say()
    say(f"  最新交易日：{今天}")
    say()

    # ROE 门槛的锚 = 历年截面中位数的中位数（只用已发生的数据）
    say("  正在计算 ROE 门槛锚点（逐年取截面中位，约 20 秒）...")
    年末 = []
    for y in range(int(今天[:4]) - 15, int(今天[:4]) + 1):
        候 = [d for d in D.交易日 if d[:4] == str(y)]
        if 候:
            年末.append(候[-1])
    ROE历史 = []
    for d in 年末:
        try:
            Fd = E.截面因子(D, d)
            池d, _ = E.建股票池(Fd, D, d)
            if len(池d) > 50:
                m = float(np.nanmedian(Fd.loc[池d, "roe_ttm"]))
                if np.isfinite(m):
                    ROE历史.append(m)
        except Exception:
            pass
    门槛ROE = float(np.median(ROE历史)) if ROE历史 else 8.0
    say(f"    历年截面 ROE 中位的中位数 = {门槛ROE:.2f}%（{len(ROE历史)} 个年度样本）")
    say()

    F = E.截面因子(D, 今天)
    池, 池明细 = E.建股票池(F, D, 今天)
    合格, 门槛明细 = E.合格标的(F, 池, D, 今天, 门槛ROE)
    综合分, 分组 = E.打分(F, 池)
    选中, N, 被挡, 补足 = E.选股(F, 综合分, 合格, 资金)

    bar()
    say("筛选漏斗（每一步剩多少只）")
    bar()
    for k, v in 池明细.items():
        if k.startswith("_"):
            say(f"    {k[1:]}: {v}")
        else:
            say(f"  {k:<14}{v:>7,} 只")
    say()
    say("  绝对门槛（各条单独通过数，最终取交集）")
    for k, v in 门槛明细.items():
        if k.startswith("_"):
            say(f"    {k[1:]} = {v}")
        else:
            say(f"  {k:<22}{v:>7,} 只")
    say(f"\n  四条全过（合格标的）：{len(合格):,} 只")
    say(f"  其中一手买得起的：{len(合格) - 被挡:,} 只（被价格挡掉 {被挡:,} 只）")
    if 补足:
        say("  ⚠ 没有标的能通过全部绝对门槛，本次是按综合分强行取的，"
            "不代表它们达标 —— 这种情况下更应该空仓等待")
    say()

    bar()
    say(f"候选清单（{len(选中)} 只）")
    bar()
    结果 = []
    if len(选中) == 0:
        say("  今天一只都选不出来。")
        say("  这不是故障 —— 门槛全都锚在市场分布和国债利率上，")
        say("  市场整体不便宜、或者你的资金买不起达标股票时，选不出来是正常且正确的结果。")
    else:
        每仓 = 资金 / len(选中)
        say(f"  {'代码':<11}{'名称':<9}{'现价':>8}{'一手':>8}"
            f"{'股息率':>8}{'ROE':>8}{'年化波动':>9}{'综合分位':>9}  行业")
        rank = 综合分.rank(pct=True)
        for c in 选中:
            价 = float(F.loc[c, "真实价"])
            手数 = max(1, int(每仓 // (价 * 100)))
            金额 = 手数 * 100 * 价
            行 = {
                "代码": c, "名称": str(F.loc[c, "名称"]) if "名称" in F.columns else "",
                "真实价": round(价, 2), "一手金额": round(价 * 100, 1),
                "建议手数": 手数, "下单金额": round(金额, 1),
                "股息率%": round(float(F.loc[c, "股息率"]) * 100, 2),
                "ROE%": round(float(F.loc[c, "roe_ttm"]), 2),
                "年化波动%": round(float(F.loc[c, "波动率"]) * 100, 1),
                "综合分位%": round(float(rank.get(c, np.nan)) * 100, 1),
                "行业": str(F.loc[c, "行业"]) if "行业" in F.columns else "",
            }
            for g in 分组.columns:
                行[f"{g}分位%"] = round(float(分组[g].rank(pct=True).get(c, np.nan)) * 100, 1)
            结果.append(行)
            say(f"  {c:<11}{行['名称'][:7]:<9}{价:>8.2f}{价*100:>8.0f}"
                f"{行['股息率%']:>7.2f}%{行['ROE%']:>7.2f}%{行['年化波动%']:>8.1f}%"
                f"{行['综合分位%']:>8.1f}%  {行['行业'][:6]}")
        say()
        say("  四个因子各自的分位（越高越好）")
        say(f"  {'代码':<11}" + "".join(f"{g:>10}" for g in 分组.columns))
        for 行 in 结果:
            say(f"  {行['代码']:<11}" +
                "".join(f"{行.get(f'{g}分位%', 0):>9.1f}%" for g in 分组.columns))
    say()

    # ---------- 真实下单成本 ----------
    if 结果:
        bar()
        say("这一笔真实要花多少钱")
        bar()
        总下单 = sum(r["下单金额"] for r in 结果)
        买佣金 = sum(max(r["下单金额"] * E.佣金费率, E.佣金最低) for r in 结果)
        买过户 = 总下单 * E.过户费率
        买滑点 = 总下单 * E.滑点率
        卖佣金 = 买佣金
        卖印花 = 总下单 * E.印花税率
        卖过户 = 买过户
        卖滑点 = 买滑点
        往返 = 买佣金 + 买过户 + 买滑点 + 卖佣金 + 卖印花 + 卖过户 + 卖滑点
        say(f"  下单金额合计        {总下单:>10,.1f} 元（剩余现金 {资金-总下单:,.1f} 元）")
        say(f"  买入佣金            {买佣金:>10,.2f} 元"
            f"  ← 每笔 max(金额×{E.佣金费率*10000:g}‱, {E.佣金最低:g}元)")
        say(f"  买入过户费+滑点     {买过户+买滑点:>10,.2f} 元")
        say(f"  ——（如果之后卖出）——")
        say(f"  卖出佣金            {卖佣金:>10,.2f} 元")
        say(f"  卖出印花税          {卖印花:>10,.2f} 元")
        say(f"  卖出过户费+滑点     {卖过户+卖滑点:>10,.2f} 元")
        say(f"  一买一卖总成本      {往返:>10,.2f} 元  = 下单金额的 "
            f"{往返/总下单*100:.2f}%")
        say(f"  → 这些股票要平均涨 {往返/总下单*100:.2f}% 你才回本")
        if 往返 / 总下单 > 0.015:
            say(f"  ⚠ 往返成本超过 1.5%。降低成本最有效的两个办法："
                f"把持仓数调少（每仓金额变大），或者把调仓频率调低。")
        say()

    # ---------- 诚实标注 ----------
    bar()
    say("这套规则的回测表现（必须和清单一起看）")
    bar()
    回测文件 = os.path.join(OUT, "回测结果.json")
    if os.path.exists(回测文件):
        try:
            with open(回测文件, encoding="utf-8") as f:
                bt = json.load(f)
            g = bt.get("全程", {})
            say(f"  回测区间 {g.get('起')} ~ {g.get('止')}")
            say(f"  年化 {g.get('年化', 0)*100:.2f}%   最大回撤 {g.get('最大回撤', 0)*100:.2f}%"
                f"   夏普 {g.get('夏普', 0):.2f}   月胜率 {g.get('月胜率', 0)*100:.1f}%")
            say(f"  最差连续12个月 {g.get('最差连续12个月', 0)*100:.2f}%")
            v = bt.get("验收", {})
            过 = sum(1 for x in v.values() if isinstance(x, dict) and x.get("达标"))
            say(f"  验收标准：{过}/{len([x for x in v.values() if isinstance(x, dict)])} 条达标")
            say(f"  ⚠ 那份回测用的参数不一定和你现在的 config.json 一样。")
            say(f"     改了参数就重跑 04_backtest.bat，否则这里的数字对不上你现在的规则。")
        except Exception as e:
            say(f"  （读回测结果出错：{e}）")
    else:
        say("  还没有回测结果。先跑 04_backtest.bat —— ")
        say("  没有回测的选股清单，和随便报两个代码没有本质区别。")
    say()
    say("  提醒（有出处，不是套话）：")
    say("   · 上交所 5,340 万账户数据：10万元以下账户年化跑输约 5.6 个百分点，")
    say("     其中选股拖累 4.3pp、交易成本 1.4pp（Jones et al., JFQA 2025）")
    say("   · 只持 2 只股票时，约 71% 的个股特质波动没被分散掉")
    say("   · 公募基金投资者数据：持有不足 3 个月只有 39% 的人赚钱，"
        "持有 3 年以上约 95%")
    say()

    out = {
        "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "交易日": 今天, "资金": 资金, "配置": 配置,
        "ROE门槛": round(门槛ROE, 2),
        "漏斗": 池明细, "门槛": 门槛明细,
        "合格数": int(len(合格)), "被价格挡掉": int(被挡),
        "是否补足": bool(补足), "候选": 结果,
    }
    with open(os.path.join(OUT, "今日选股.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUT, "今日选股日志.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(日志))
    bar("=")
    say(f"  完成，用时 {time.time()-t0:.0f} 秒")
    say(f"  结果已存到 output\\今日选股.json")
    bar("=")


if __name__ == "__main__":
    try:
        主()
    except KeyboardInterrupt:
        print("\n  已中断。")
    except Exception:
        import traceback
        traceback.print_exc()
    if not os.environ.get("XUANGU_NO_PAUSE"):
        input("\n  按回车关闭。")
