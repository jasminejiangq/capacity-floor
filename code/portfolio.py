# -*- coding: utf-8 -*-
"""
我的持仓分析
============
把你实际买的（或打算买的）股票填进 my_portfolio.json，这个脚本回答四件事：

  1. 这笔交易的真实成本是多少？要涨多少才回本？
  2. 这些股票，按你自己设定的规则，今天还合格吗？卡在哪一条？
  3. 这个组合分散得够不够？行业挤在一起了吗？
  4. 如果过去几年一直持有这个组合，会是什么结果？（含幸存者偏差警告）

刻意不做的事：
  不给「现在该买/该卖」的建议。这个脚本只告诉你「你自己定的规则，
  对这些股票是什么判断」——判断是规则做的，决定是你做的。
"""
import os, sys, json, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
import settings as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
持仓文件 = os.path.join(ROOT, "my_portfolio.json")
os.makedirs(OUT, exist_ok=True)

日志 = []


def say(m=""):
    print(m, flush=True)
    日志.append(str(m))


def bar(ch="-"):
    say(ch * 68)


def 规范代码(c):
    """600375 / sh.600375 / SH600375 都能认。"""
    c = str(c).strip().lower().replace(" ", "")
    for 前 in ("sh.", "sz.", "sh", "sz"):
        if c.startswith(前):
            c = c[len(前):]
            break
    c = "".join(ch for ch in c if ch.isdigit()).zfill(6)
    市 = "sh" if c[:2] in ("60", "68") else "sz"
    return f"{市}.{c}", c


def 一笔成本(金额, 方向, 算滑点=True):
    """返回 (费用合计, 明细dict)。

    关于滑点：它不是付给谁的费用，而是「你想要的价格」和「实际成交价」的差。
    对<b>已经成交</b>的交易，滑点早就体现在成交价里了，再算一遍就是重复计算；
    所以分析已持仓时 算滑点=False。
    对<b>还没买</b>的计划，滑点是要预留的，算进去才不会低估成本。
    """
    佣 = max(金额 * E.佣金费率, E.佣金最低)
    过户 = 金额 * E.过户费率
    滑 = 金额 * E.滑点率 if 算滑点 else 0.0
    印 = 金额 * E.印花税率 if 方向 == "卖" else 0.0
    明 = {"佣金": round(佣, 2), "印花税": round(印, 2), "过户费": round(过户, 3)}
    if 算滑点:
        明["滑点"] = round(滑, 2)
    return 佣 + 过户 + 滑 + 印, 明


def 主():
    t0 = time.time()
    配置 = S.读配置()
    E.应用配置(配置)

    bar("=")
    say("   我的持仓分析")
    bar("=")
    if not os.path.exists(持仓文件):
        say(f"  没找到 {持仓文件}")
        say("  请先在项目根目录建一个 my_portfolio.json，把你买的股票填进去。")
        return
    with open(持仓文件, encoding="utf-8") as f:
        我的 = json.load(f)

    持仓 = [x for x in 我的.get("持仓", []) if str(x.get("代码", "")).strip()]
    计划 = [x for x in 我的.get("计划买入", []) if str(x.get("代码", "")).strip()]
    if not 持仓 and not 计划:
        say("  my_portfolio.json 里没有任何股票。")
        return
    say(f"  已持有 {len(持仓)} 只，计划买入 {len(计划)} 只")
    say()

    D = E.数据(起始="2010-01-01", 说=say)
    今天 = D.交易日[-1]
    say()
    say(f"  数据库最新交易日：{今天}")
    if 持仓:
        最晚 = max((str(x.get("买入日期") or "") for x in 持仓), default="")
        if 最晚 and 最晚 > 今天:
            say(f"  ⚠ 你的买入日期 {最晚} 晚于数据库最新日 {今天}，"
                f"说明数据库该更新了（双击 07_每日更新.bat）")
    say()

    F = E.截面因子(D, 今天)
    池, 池明细 = E.建股票池(F, D, 今天)

    # ROE 门槛锚点：历年截面中位的中位
    ROE历史 = []
    for y in range(int(今天[:4]) - 15, int(今天[:4]) + 1):
        候 = [d for d in D.交易日 if d[:4] == str(y)]
        if not 候:
            continue
        try:
            Fd = E.截面因子(D, 候[-1])
            池d, _ = E.建股票池(Fd, D, 候[-1])
            if len(池d) > 50:
                m = float(np.nanmedian(Fd.loc[池d, "roe_ttm"]))
                if np.isfinite(m):
                    ROE历史.append(m)
        except Exception:
            pass
    门槛ROE = float(np.median(ROE历史)) if ROE历史 else 8.0
    合格, 门槛明细 = E.合格标的(F, 池, D, 今天, 门槛ROE)
    综合分, 分组 = E.打分(F, 池)
    排名 = 综合分.rank(pct=True)
    无风险 = D.取无风险利率(今天) / 100.0

    结果 = {"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "交易日": 今天,
            "持仓": [], "计划": [], "配置": 配置}

    # ══════════════════════════════════════════════════
    # 一、真实成本核算
    # ══════════════════════════════════════════════════
    bar()
    say("一、这笔交易的真实成本")
    bar()
    say(f"  你的费率设置：佣金 {E.佣金费率*10000:g}‱（单笔最低 {E.佣金最低:g} 元）"
        f"，印花税 {E.印花税率*100:g}%（卖出），过户费 {E.过户费率*100:g}%（双边）")
    say(f"  滑点按 {E.滑点率*100:g}% 单边估算（实际成交价与挂单价的偏离）")
    say()
    总投入 = 0.0
    for x in 持仓:
        码, 六 = 规范代码(x["代码"])
        股数 = float(x.get("股数") or 0)
        成本价 = float(x.get("成本价") or 0)
        现价 = float(F.loc[码, "真实价"]) if 码 in F.index else np.nan
        名 = str(F.loc[码, "名称"]) if (码 in F.index and "名称" in F.columns) \
            else str(x.get("名称备注", ""))
        say(f"  【{名} {码}】{股数:.0f} 股")
        if 成本价 > 0:
            持仓成本额 = 成本价 * 股数
            say(f"    券商显示的成本价 {成本价:.3f} 元/股 → 持仓成本 {持仓成本额:,.2f} 元")
            say(f"    注意：券商的「成本价」一般已经含了买入手续费。反推成交价：")
            for 试 in (E.佣金最低, 0.0):
                成交额 = 持仓成本额 - 试
                if 成交额 > 0:
                    say(f"      若买入费用 {试:.2f} 元 → 实际成交价约 "
                        f"{成交额/股数:.3f} 元/股")
        if np.isfinite(现价):
            市值 = 现价 * 股数
            已成交 = 成本价 > 0
            基数 = 成本价 * 股数 if 已成交 else 市值
            # 已成交：滑点已经在成交价里了，不重复算。未成交：要预留。
            买费, 买明 = 一笔成本(基数, "买", 算滑点=not 已成交)
            卖费, 卖明 = 一笔成本(市值, "卖", 算滑点=not 已成交)
            往返 = 买费 + 卖费
            say(f"    最新价 {现价:.3f} 元/股 → 市值 {市值:,.2f} 元")
            say(f"    买入费用 {买费:.2f} 元 = " +
                " + ".join(f"{k} {v}" for k, v in 买明.items() if v))
            say(f"    卖出费用 {卖费:.2f} 元 = " +
                " + ".join(f"{k} {v}" for k, v in 卖明.items() if v))
            if 已成交:
                say(f"      （已成交，滑点已体现在成交价里，不重复计算）")
            say(f"    一买一卖总成本 {往返:.2f} 元 = 本金的 {往返/基数*100:.2f}%")
            if 已成交:
                # 解方程：100P - 卖出佣金 - 印花税(100P) - 过户费(100P) = 持仓成本
                r = E.印花税率 + E.过户费率
                回本额 = (基数 + E.佣金最低) / (1 - r)
                if 回本额 * E.佣金费率 > E.佣金最低:      # 金额大到费率超过最低佣金
                    回本额 = 基数 / (1 - r - E.佣金费率)
                回本价 = 回本额 / 股数
                say(f"    ★ 回本价：卖到 {回本价:.3f} 元/股 才不亏"
                    f"（比持仓成本价高 {(回本价/成本价-1)*100:.2f}%）")
                say(f"      当前 {现价:.3f}，距回本还差 {(回本价/现价-1)*100:+.2f}%")
            if 往返 / 基数 > 0.02:
                say(f"    ⚠ 往返成本 {往返/基数*100:.2f}% —— 这笔金额太小，"
                    f"5 元最低佣金占了大头。同样一笔钱买得越少笔，这个比例越低。")
            总投入 += 基数
        else:
            say(f"    ！数据库里查不到 {码}，可能是新股、已退市、或者代码填错了")
        say()
    结果["总投入"] = round(总投入, 2)

    # ══════════════════════════════════════════════════
    # 二、按你自己的规则，这些股票合格吗
    # ══════════════════════════════════════════════════
    bar()
    say("二、按你设定的规则，它们今天合格吗")
    bar()
    say(f"  当前 10 年国债 {无风险*100:.2f}%，ROE 门槛 {门槛ROE:.2f}%（历年截面中位的中位）")
    say()
    全部 = [(规范代码(x["代码"])[0], str(x.get("名称备注", "")), "已持有") for x in 持仓] + \
           [(规范代码(x["代码"])[0], str(x.get("名称备注", "")), "计划") for x in 计划]
    for 码, 备注, 类型 in 全部:
        名 = str(F.loc[码, "名称"]) if (码 in F.index and "名称" in F.columns) else 备注
        say(f"  【{名} {码}】（{类型}）")
        if 码 not in F.index:
            say("    数据库里没有这只股票，无法判断")
            say()
            continue
        f = F.loc[码]
        # 股票池逐条
        卡住 = []
        if not (np.isfinite(f["真实价"]) and f["真实价"] > 0):
            卡住.append("没有有效价格")
        if f.get("有效天数", 999) < 200:
            卡住.append("历史数据不足 200 天")
        if f.get("上市天数", 9999) < E.最少上市天数:
            卡住.append(f"上市不足 {E.最少上市天数} 天（次新股）")
        if E.剔除ST and f.get("ST", 0) == 1:
            卡住.append("是 ST / *ST 股")
        if f.get("可交易", 1) != 1:
            卡住.append("停牌中")
        if 码 in 池:
            say("    ✓ 进入股票池（市值、流动性、估值三道筛都过了）")
        else:
            mv = f.get("流通市值", np.nan)
            if np.isfinite(mv):
                界 = F.loc[池, "流通市值"].min() if len(池) else np.nan
                if np.isfinite(界) and mv < 界:
                    卡住.append(f"流通市值 {mv/1e8:.1f} 亿，低于本期市值门槛约 {界/1e8:.1f} 亿")
            if not 卡住:
                卡住.append("被流动性或估值筛剔除")
            say(f"    ✗ 没进股票池：{'；'.join(卡住)}")
        # 四条绝对门槛
        条 = []
        if E.门槛开关.get("ROE", True):
            v = f.get("roe_ttm", np.nan)
            条.append(("ROE 高于历史中位", v, 门槛ROE, "%",
                       np.isfinite(v) and v > 门槛ROE))
        if E.门槛开关.get("股息", True):
            倍 = float(E.门槛开关.get("股息倍数", 1.0))
            v = f.get("股息率", np.nan)
            条.append((f"股息率 高于国债×{倍:g}", (v or 0) * 100, 无风险 * 倍 * 100, "%",
                       np.isfinite(v) and v > 无风险 * 倍))
        if E.门槛开关.get("波动", True):
            v = f.get("波动率", np.nan)
            界 = F.loc[池, "波动率"].quantile(E.波动率门槛分位) if len(池) else np.nan
            条.append((f"波动率 低于{E.波动率门槛分位*100:.0f}分位", (v or 0) * 100,
                       (界 or 0) * 100, "%", np.isfinite(v) and np.isfinite(界) and v < 界))
        if E.门槛开关.get("EP", True):
            v = f.get("EP", np.nan)
            条.append(("EP 为正（不买亏损股）", v, 0.0, "", np.isfinite(v) and v > 0))
        for 名2, 实, 要, 单, 过 in 条:
            实s = f"{实:.2f}{单}" if np.isfinite(实) else "无数据"
            要s = f"{要:.2f}{单}" if np.isfinite(要) else "—"
            say(f"    {'✓' if 过 else '✗'} {名2:<22}实际 {实s:>10}   门槛 {要s:>10}")
        合 = 码 in 合格
        say(f"    → {'✓ 四条全过，是合格标的' if 合 else '✗ 不是合格标的'}")
        if 码 in 排名.index and np.isfinite(排名.get(码, np.nan)):
            say(f"    综合分位 {排名[码]*100:.1f}%（越高越好）；"
                + "  ".join(f"{g} {分组[g].rank(pct=True).get(码, np.nan)*100:.0f}%"
                            for g in 分组.columns
                            if np.isfinite(分组[g].rank(pct=True).get(码, np.nan))))
        结果["持仓" if 类型 == "已持有" else "计划"].append({
            "代码": 码, "名称": 名, "进入股票池": bool(码 in 池),
            "是合格标的": bool(合),
            "综合分位%": round(float(排名.get(码, np.nan)) * 100, 1)
            if np.isfinite(排名.get(码, np.nan)) else None,
        })
        say()

    # ══════════════════════════════════════════════════
    # 三、分散度
    # ══════════════════════════════════════════════════
    bar()
    say("三、分散度")
    bar()
    N = len(持仓) + len(计划)
    残余 = 100.0 / np.sqrt(N) if N else 0
    say(f"  持仓/计划合计 {N} 只")
    say(f"  等权组合的残余个股特质波动 ≈ {残余:.1f}%（1/√N）")
    say(f"    对照：1只 100%   2只 70.7%   3只 57.7%   5只 44.7%   10只 31.6%")
    say(f"  唯一一篇直接研究中国市场的实证（Stotz & Lu, 2014，2300只A股）：")
    say(f"    10 只股票只消除 67% 的非系统性风险，作者建议 8 只为折中点。")
    if N <= 2:
        say(f"  ⚠ 只持 {N} 只，个股特质风险几乎没被分散。单只踩雷就是全部亏损。")
    行业 = {}
    for 码, _, _ in 全部:
        if 码 in F.index and "行业" in F.columns:
            行业[str(F.loc[码, "行业"])] = 行业.get(str(F.loc[码, "行业"]), 0) + 1
    if 行业:
        say(f"  行业分布：" + "  ".join(f"{k} {v}只" for k, v in
                                        sorted(行业.items(), key=lambda x: -x[1])))
        最大 = max(行业.values()) / max(N, 1)
        if 最大 > E.单行业上限:
            say(f"  ⚠ 单一行业占 {最大*100:.0f}%，超过你设定的上限 "
                f"{E.单行业上限*100:.0f}%")
    say()

    # ══════════════════════════════════════════════════
    # 四、这个组合过去表现如何
    # ══════════════════════════════════════════════════
    bar()
    say("四、如果过去一直持有这个组合")
    bar()
    say("  ⚠ 先说清楚这段该怎么读：")
    say("    这是「用今天知道的股票，回头看过去」，天然带后视偏差 ——")
    say("    你是在知道这些公司活到了今天、没退市、没暴雷的前提下选的它们。")
    say("    所以下面的数字系统性偏乐观，只能当参考，不能当预期收益。")
    say()
    码们 = [c for c, _, _ in 全部 if c in D.收盘.columns]
    if not 码们:
        say("  没有可用的股票，跳过。")
    else:
        for 年数 in (1, 3, 5):
            起i = max(0, len(D.交易日) - int(年数 * 244))
            起日 = D.交易日[起i]
            收 = D.收盘.iloc[起i:][码们]
            有 = 收.columns[收.iloc[0].notna() &收.iloc[-1].notna()]
            if len(有) == 0:
                say(f"  近 {年数} 年：这些股票当时还没上市，无法比较")
                continue
            个股 = (收[有].iloc[-1] / 收[有].iloc[0] - 1)
            组合 = float(个股.mean())
            基 = D.指数[D.指数["code"] == "sh.000300"].set_index("date")["close"]
            基 = 基[(基.index >= 起日)]
            基收 = float(基.iloc[-1] / 基.iloc[0] - 1) if len(基) > 1 else np.nan
            say(f"  近 {年数} 年（{起日} 起，{len(有)}/{len(码们)} 只有数据）：")
            say(f"    等权组合 {组合*100:+.1f}%    沪深300 {基收*100:+.1f}%"
                f"    超额 {(组合-基收)*100:+.1f} 个百分点")
            for c in 有:
                名 = str(F.loc[c, "名称"]) if (c in F.index and "名称" in F.columns) else c
                say(f"      {名:<8}{c:<12}{个股[c]*100:+8.1f}%")
        say()
        say("  这些是「后复权」价格算的，已经把分红再投资算进去了。")
    say()

    bar("=")
    say(f"  完成，用时 {time.time()-t0:.0f} 秒")
    say()
    say("  这份分析没有给你任何「该买/该卖」的结论 —— 那是你的决定。")
    say("  它只做两件事：把真实成本算清楚，把你自己定的规则对这些股票的判断摆出来。")
    bar("=")

    with open(os.path.join(OUT, "我的持仓分析.json"), "w", encoding="utf-8") as f:
        json.dump(结果, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUT, "我的持仓分析.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(日志))
    say("  结果已存到 output\\我的持仓分析.json")


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
