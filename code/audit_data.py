# -*- coding: utf-8 -*-
"""
第三步之前的数据验收（约 2-5 分钟，只读不改）

建库完成了，但完成不等于可用。回测一旦建立在错的数据口径上，
跑出来的漂亮曲线比跑不出来更危险 —— 因为你会信它。
所以在回测之前，把几件必须用数据回答的事一次问清楚。

本脚本回答 6 个问题：
  1. 那 57 只"日线失败"到底是什么？会不会有真数据缺口？
  2. 分红能不能相加？（决定股息率怎么算，红利因子 0.7 权重压在这上面）
  3. 分红表里有没有"预披露"这种没有金额的占位行？
  4. 三种股息率口径算出来分别长什么样？跟外部已知数字对不对得上？
  5. PIT 有没有漏 —— 有没有"公告日早于报告期"这种未来函数？
  6. 2500 元到底能在"达标股票池"里买到几只？（这是整个项目的成败点）
"""
import os, sys, json, time, sqlite3
import numpy as np
import pandas as pd

本目录 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(本目录, "data", "ashare.db")
输出目录 = os.path.join(本目录, "output")
os.makedirs(输出目录, exist_ok=True)

结果, 日志 = {}, []


def say(s=""):
    print(s, flush=True)
    日志.append(str(s))


def bar(ch="-"):
    say(ch * 66)


def 六位(s):
    return s.astype(str).str.split(".").str[-1]


t0 = time.time()
c = sqlite3.connect(DB)
bar("=")
say("   数据验收 · 回测之前的最后一道关")
bar("=")
say(f"   库：{DB}")
say(f"   大小：{os.path.getsize(DB)/1024**3:.2f} GB")
say()

# ══════════════════════════════════════════════════════════════
# 问题 1：57 只日线"失败"是什么
# ══════════════════════════════════════════════════════════════
bar()
say("问题 1  那些「日线失败」的股票，是真缺口还是本来就不该下？")
bar()
失败 = pd.read_sql(
    "SELECT p.key AS code, p.status, p.note, b.name, b.ipo_date, b.out_date "
    "FROM progress p LEFT JOIN stock_basic b ON b.code = p.key "
    "WHERE p.task='daily' AND p.status <> 'ok'", c)
say(f"  progress 里非 ok 的日线记录：{len(失败)} 条")
if len(失败):
    有退市日 = 失败["out_date"].astype(str).str.strip().str.len() == 10
    退市早 = 有退市日 & (失败["out_date"].astype(str) < "2010-01-01")
    say(f"    其中 2010-01-01 之前就已退市：{int(退市早.sum())} 只")
    say(f"    → 这些股票在回测窗口（2010 起）里一根K线都不该有，下不到是正常的")
    可疑 = 失败[~退市早]
    say(f"    需要关注的（不是早退市的）：{len(可疑)} 只")
    if len(可疑):
        say()
        say(f"    {'代码':<12}{'名称':<10}{'上市日':<12}{'退市日':<12}{'原因'}")
        for _, r in 可疑.head(25).iterrows():
            say(f"    {str(r['code']):<12}{str(r['name'] or '')[:8]:<10}"
                f"{str(r['ipo_date'] or '')[:10]:<12}{str(r['out_date'] or '—')[:10]:<12}"
                f"{str(r['note'] or '')[:40]}")
    else:
        say("    ✓ 一只都没有 —— 57 只全是 2010 年前的退市股，没有真数据缺口")
    结果["日线失败"] = {"总数": len(失败), "早退市": int(退市早.sum()),
                       "可疑": len(可疑), "可疑清单": 可疑["code"].tolist()[:50]}
say()

# ══════════════════════════════════════════════════════════════
# 问题 2：分红能不能相加（决定性检验）
# ══════════════════════════════════════════════════════════════
bar()
say("问题 2  年报分红和中期分红，能不能相加？")
bar()
say("  判别逻辑（这次用的是逻辑硬约束，不是拍脑袋的阈值）：")
say("    如果「年报那条已经包含了当年的中期分红」（不可加），")
say("    那么中期 ⊂ 年报，必然有 中期 ≤ 年报 对每一家公司恒成立。")
say("    只要存在相当比例的 中期 > 年报，包含关系就被证伪 —— 两者是独立的两笔钱。")
say()

div = pd.read_sql(
    "SELECT code, report_date, plan_ann_date, cash_per10, progress FROM dividend", c)
div["年"] = div["report_date"].str[:4]
div["期"] = div["report_date"].str[4:]
有钱 = div[div["cash_per10"].fillna(0) > 0]

年报 = 有钱[有钱["期"] == "1231"][["code", "年", "cash_per10"]].rename(
    columns={"cash_per10": "年报派息"})
中期 = (有钱[有钱["期"] != "1231"]
        .groupby(["code", "年"], as_index=False)["cash_per10"].sum()
        .rename(columns={"cash_per10": "中期合计"}))
配对 = 年报.merge(中期, on=["code", "年"], how="inner")

say(f"  同一年既有年报分红、又有中期分红的 公司×年 组合：{len(配对):,} 对")
if len(配对) >= 30:
    超出 = (配对["中期合计"] > 配对["年报派息"] * 1.001)
    比例 = 超出.mean()
    say(f"  其中「中期 > 年报」的：{int(超出.sum()):,} 对，占 {比例*100:.1f}%")
    say()
    极端 = 配对.assign(倍数=配对["中期合计"] / 配对["年报派息"]).nlargest(6, "倍数")
    say(f"    最极端的几个反例：")
    say(f"    {'代码':<10}{'年份':<8}{'年报每10股':>12}{'中期每10股':>12}{'倍数':>8}")
    for _, r in 极端.iterrows():
        say(f"    {r['code']:<10}{r['年']:<8}{r['年报派息']:>12.4f}"
            f"{r['中期合计']:>12.4f}{r['倍数']:>8.2f}")
    say()
    if 比例 > 0.15:
        判定 = "可加"
        say(f"  ✅ 判定：可以相加。")
        say(f"     有 {比例*100:.1f}% 的组合里中期金额大于年报金额。如果年报那条")
        say(f"     真的包含了中期，这在算术上不可能发生（部分不可能大于整体）。")
        say(f"     所以两者是各自独立的分配方案 —— 全年分红 = 各期之和。")
    else:
        判定 = "存疑"
        say(f"  ⚠ 判定：存疑。中期超过年报的比例只有 {比例*100:.1f}%，")
        say(f"     不足以证伪包含关系。先别相加，把这段发给 Claude。")
    结果["分红可加性"] = {"配对数": len(配对), "中期大于年报占比": round(float(比例), 4),
                         "判定": 判定}
else:
    结果["分红可加性"] = {"配对数": len(配对), "判定": "样本不足"}
    say("  配对太少，判不了。")
say()

# ══════════════════════════════════════════════════════════════
# 问题 3：方案进度（有没有没金额的占位行）
# ══════════════════════════════════════════════════════════════
bar()
say("问题 3  分红表里有没有「预披露」这种只有意向、没有金额的行？")
bar()
进度 = div.groupby(div["progress"].fillna("（空）"))["code"].count().sort_values(ascending=False)
say(f"  {'方案进度':<16}{'条数':>10}{'其中金额为空':>14}")
for k, n in 进度.head(12).items():
    空 = int(div[(div["progress"].fillna("（空）") == k) &
                 (div["cash_per10"].isna())].shape[0])
    say(f"  {str(k)[:14]:<16}{n:>10,}{空:>14,}")
无金额 = int(div["cash_per10"].isna().sum())
say()
say(f"  金额为空的行共 {无金额:,} 条（{无金额/max(len(div),1)*100:.1f}%）"
    f" —— 回测里会被当作 0，不影响求和")
结果["方案进度"] = {str(k): int(v) for k, v in 进度.head(12).items()}
say()

# ══════════════════════════════════════════════════════════════
# 问题 4：三种股息率口径对比
# ══════════════════════════════════════════════════════════════
bar()
say("问题 4  三种口径算出来的股息率，跟外部已知数字对得上吗？")
bar()
最新日 = c.execute("SELECT MAX(date) FROM daily").fetchone()[0]
日 = pd.read_sql(
    "SELECT code, amount, volume, turn, is_st, trade_status FROM daily WHERE date=?",
    c, params=[最新日])
日["六位"] = 六位(日["code"])
日["真实价"] = 日["amount"] / 日["volume"].replace(0, np.nan)
日["流通市值"] = 日["amount"] * 100.0 / 日["turn"].replace(0, np.nan)
日 = 日[np.isfinite(日["真实价"]) & (日["真实价"] > 0)]
say(f"  估值日：{最新日}，有效股票 {len(日):,} 只")
say()

div["plan_dt"] = pd.to_datetime(div["plan_ann_date"], errors="coerce")
可见 = div[div["plan_dt"].notna() & (div["plan_dt"] <= 最新日)].copy()
可见["派息"] = 可见["cash_per10"].fillna(0)

# 口径A：只用最近一条年报
A = (可见[可见["期"] == "1231"].sort_values("report_date")
     .groupby("code").tail(1).set_index("code")["派息"] / 10.0)
# 口径B：滚动 12 个月（按预案公告日）
起 = pd.Timestamp(最新日) - pd.Timedelta(days=365)
B = 可见[可见["plan_dt"] > 起].groupby("code")["派息"].sum() / 10.0
# 口径C：财年归集 —— 取「年报预案已公告」的最近那个财年，合计该财年各期
年报已公告 = 可见[可见["期"] == "1231"].groupby("code")["年"].max().rename("基准年")
C = (可见.merge(年报已公告, left_on="code", right_index=True)
     .query("年 == 基准年").groupby("code")["派息"].sum() / 10.0)

def 口径(名, s):
    t = 日.set_index("六位").join(s.rename("每股股息"), how="left")
    t["每股股息"] = t["每股股息"].fillna(0.0)
    t["股息率"] = t["每股股息"] / t["真实价"]
    分红总额 = (t["每股股息"] * t["流通市值"] / t["真实价"]).sum()
    整体法 = 分红总额 / t["流通市值"].sum() if t["流通市值"].sum() else np.nan
    有息 = t[t["股息率"] > 0]["股息率"]
    return {"派息公司数": int((t["每股股息"] > 0).sum()),
            "全市场中位%": round(float(t["股息率"].median()) * 100, 3),
            "派息股中位%": round(float(有息.median()) * 100, 3) if len(有息) else None,
            "整体法%": round(float(整体法) * 100, 3),
            "超过5%的只数": int((t["股息率"] > 0.05).sum())}

三 = {"A 只算年报（现状）": 口径("A", A),
      "B 滚动12个月": 口径("B", B),
      "C 财年归集（推荐）": 口径("C", C)}
say(f"  {'口径':<20}{'派息公司':>9}{'全市场中位':>11}{'派息股中位':>11}{'整体法':>9}{'>5%只数':>9}")
for k, v in 三.items():
    say(f"  {k:<20}{v['派息公司数']:>9,}{v['全市场中位%']:>10.2f}%"
        f"{(v['派息股中位%'] or 0):>10.2f}%{v['整体法%']:>8.2f}%{v['超过5%的只数']:>9,}")
结果["股息率三口径"] = 三
say()
say("  外部锚点（用来交叉验证，来源见 研究来源登记表.md）：")
say("    · 中证全指 000985 官方股息率（整体法）  1.56%   （2026-08-31）")
say("    · A股 2025 年度分红对应股息率            1.8%    （中金，2026-05）")
say("    · 中证红利 000922 官方股息率             4.07%   （2026-08-31）")
say("    · 全市场等权中位数应显著低于整体法（约 1/3 公司完全不分红）")
say()
for k, v in 三.items():
    整 = v["整体法%"]
    评 = ("✓ 落在合理区间" if 1.0 <= 整 <= 2.5 else
          "⚠ 明显偏高，怀疑重复计算" if 整 > 2.5 else
          "⚠ 明显偏低，怀疑漏了分红")
    say(f"    {k:<20}整体法 {整:>5.2f}%  {评}")
say()

# ══════════════════════════════════════════════════════════════
# 问题 5：PIT 完整性（未来函数体检）
# ══════════════════════════════════════════════════════════════
bar()
say("问题 5  有没有「公告日早于报告期」这种未来函数？")
bar()
fin = pd.read_sql("SELECT report_date, ann_date FROM finance "
                  "WHERE ann_date IS NOT NULL AND ann_date <> ''", c)
fin["r"] = pd.to_datetime(fin["report_date"], format="%Y%m%d", errors="coerce")
fin["a"] = pd.to_datetime(fin["ann_date"], errors="coerce")
fin = fin.dropna(subset=["r", "a"])
fin["延迟"] = (fin["a"] - fin["r"]).dt.days
提前 = int((fin["延迟"] < 0).sum())
say(f"  财务：{len(fin):,} 条有公告日")
say(f"    公告日早于报告期（未来函数）：{提前:,} 条  {'✓ 干净' if 提前 == 0 else '✗ 有问题！'}")
say(f"    公告延迟天数  中位 {fin['延迟'].median():.0f} 天，"
    f"5%分位 {fin['延迟'].quantile(0.05):.0f} 天，95%分位 {fin['延迟'].quantile(0.95):.0f} 天")

# —— 5b：公告延迟为什么是 396 天，改成「可用日」之后会怎样 ——
say()
say(f"  ── 财务公告日的口径核查（实测延迟中位 {fin['延迟'].median():.0f} 天，正常应在 30~120 天）──")
fin["期"] = fin["report_date"].astype(str).str[4:]
名 = {"0331": "一季报", "0630": "中报", "0930": "三季报", "1231": "年报"}
截止天 = {"0331": 30, "0630": 62, "0930": 31, "1231": 120}
say(f"    {'报告期':<8}{'条数':>9}{'延迟中位':>10}{'法定截止约':>12}{'落在1年后附近占比':>18}")
for k in ("0331", "0630", "0930", "1231"):
    g = fin[fin["期"] == k]
    if not len(g):
        continue
    一年后 = ((g["延迟"] >= 330) & (g["延迟"] <= 460)).mean()
    say(f"    {名[k]:<8}{len(g):>9,}{g['延迟'].median():>9.0f}天"
        f"{截止天[k]:>11}天{一年后*100:>17.1f}%")
聚 = ((fin["延迟"] >= 330) & (fin["延迟"] <= 460)).mean()
say()
say(f"    延迟落在 330~460 天（即「整整晚一年」）的比例：{聚*100:.1f}%")
if 聚 > 0.35:
    say("    ✓ 证实：ann_date 是东财的「最新公告日期」，被下一年同期报告顶到了一年后，")
    say("      不是真实首次披露日。engine 已改用 min(ann_date, 法定披露截止日)。")
else:
    say("    ⚠ 没有明显的「晚一年」聚集，原因可能另有其他，把这段发给 Claude。")

# 新口径下会早多少
截止映射 = {"0331": ("同", "-04-30"), "0630": ("同", "-08-31"),
            "0930": ("同", "-10-31"), "1231": ("次", "-04-30")}
截止 = pd.Series(pd.NaT, index=fin.index, dtype="datetime64[ns]")
年 = pd.to_numeric(fin["report_date"].astype(str).str[:4], errors="coerce")
for k, (哪, 月日) in 截止映射.items():
    m = fin["期"] == k
    if m.any():
        y = 年[m] + (1 if 哪 == "次" else 0)
        截止.loc[m] = pd.to_datetime(y.astype("Int64").astype(str) + 月日,
                                     errors="coerce")
可用 = fin["a"].where(fin["a"] < 截止, 截止)
新延迟 = (可用 - fin["r"]).dt.days
say()
say(f"    改用「可用日」之后的延迟：中位 {新延迟.median():.0f} 天"
    f"（原 {fin['延迟'].median():.0f} 天），"
    f"平均提前 {(fin['延迟'] - 新延迟).mean():.0f} 天看到财报")
say(f"    可用日早于真实首次披露的风险：可用日 = min(两个上界)，"
    f"仍然 >= 真实披露日，不会提前偷看")
结果["财务公告口径"] = {"原延迟中位": float(fin["延迟"].median()),
                       "新延迟中位": float(新延迟.median()),
                       "晚一年聚集占比": round(float(聚), 4)}
say()

d2 = div.dropna(subset=["plan_dt"]).copy()
d2["r"] = pd.to_datetime(d2["report_date"], format="%Y%m%d", errors="coerce")
d2 = d2.dropna(subset=["r"])
d2["延迟"] = (d2["plan_dt"] - d2["r"]).dt.days
提前2 = int((d2["延迟"] < 0).sum())
say(f"  分红：{len(d2):,} 条有预案公告日")
say(f"    预案公告日早于报告期：{提前2:,} 条")
if 提前2:
    早 = d2[d2["延迟"] < 0]
    季度占比 = (早["期"] != "1231").mean()
    say(f"      其中季度/中期报告期占 {季度占比*100:.1f}%，年报期占 {(1-季度占比)*100:.1f}%")
    say(f"      提前天数：中位 {早['延迟'].median():.0f} 天，最多提前 {-早['延迟'].min():.0f} 天")
    if 季度占比 > 0.8:
        say("      ✓ 正常：中期分红预案常在报告期结束之前就公告（比如 6 月底的中报，")
        say("        方案可能 5 月就定了）。回测用的是 预案公告日 本身，")
        say("        也就是市场真正知道的那天 —— 这不是未来函数。")
    else:
        say("      ⚠ 年报期也大量提前，不正常，把这段发给 Claude。")
say(f"    公告延迟天数  中位 {d2['延迟'].median():.0f} 天")
ind = pd.read_sql("SELECT snapshot_date, COUNT(*) n FROM industry GROUP BY 1 ORDER BY 1", c)
say(f"  行业快照：{len(ind)} 个，{ind['snapshot_date'].iloc[0]} ~ {ind['snapshot_date'].iloc[-1]}")
结果["PIT"] = {"财务未来函数": 提前, "分红未来函数": 提前2,
               "财务公告延迟中位天": float(fin["延迟"].median()),
               "行业快照数": len(ind)}
say()

# ══════════════════════════════════════════════════════════════
# 问题 6：2500 元能在「达标池」里买到几只（成败点）
# ══════════════════════════════════════════════════════════════
bar()
say("问题 6  2500 元，在「过了所有筛选的股票」里能买到几只？")
bar()
u = 日.copy()
步 = []
u = u[(u["is_st"].fillna(0) == 0)]
步.append(("剔除 ST", len(u)))
u = u[(u["trade_status"].fillna(1) == 1)]
步.append(("剔除停牌", len(u)))
基 = pd.read_sql("SELECT code, ipo_date, out_date FROM stock_basic WHERE type='1'", c)
基["六位"] = 六位(基["code"])
基["ipo"] = pd.to_datetime(基["ipo_date"], errors="coerce")
u = u.merge(基[["六位", "ipo", "out_date"]], on="六位", how="left")
u = u[u["out_date"].astype(str).str.strip().str.len() != 10]
步.append(("剔除已退市", len(u)))
u = u[(pd.Timestamp(最新日) - u["ipo"]).dt.days >= 252]
步.append(("剔除上市不足252天", len(u)))
mv界 = u["流通市值"].quantile(0.30)
u = u[u["流通市值"] > mv界]
步.append((f"剔除最小30%市值(<{mv界/1e8:.1f}亿)", len(u)))
amt界 = u["amount"].quantile(0.10)
u = u[u["amount"] > amt界]
步.append(("剔除成交额最低10%", len(u)))

for 名, n in 步:
    say(f"    {名:<30}剩 {n:>6,} 只")
say()
u["一手"] = u["真实价"] * 100
say(f"  达标池 {len(u):,} 只，一手金额：中位 {u['一手'].median():,.0f} 元，"
    f"最低 {u['一手'].min():,.0f} 元")
say()
say(f"  {'目标持股数 N':<14}{'每只预算':>10}{'达标池里买得起':>16}{'占达标池':>10}")
可行 = {}
for N in (1, 2, 3, 4, 5, 6, 8, 10):
    预算 = 2500 / N
    买得起 = int((u["一手"] <= 预算).sum())
    可行[N] = {"每只预算": round(预算), "买得起": 买得起,
               "占比%": round(买得起 / max(len(u), 1) * 100, 1)}
    标 = ""
    if 买得起 >= N * 10:
        标 = "  ← 选得出来，且有挑选余地"
    elif 买得起 >= N:
        标 = "  ← 勉强够数，几乎没得挑"
    else:
        标 = "  ← 凑不满"
    say(f"  {N:<14}{预算:>10,.0f}{买得起:>16,}{可行[N]['占比%']:>9.1f}%{标}")
结果["小资金可行性"] = {"达标池": len(u), "一手中位": float(u["一手"].median()),
                       "按N": 可行, "筛选步骤": 步}
say()

c.close()
bar("=")
say(f"  验收完成，耗时 {time.time()-t0:.0f} 秒")
bar("=")
with open(os.path.join(输出目录, "数据验收结果.json"), "w", encoding="utf-8") as f:
    json.dump(结果, f, ensure_ascii=False, indent=2, default=str)
with open(os.path.join(输出目录, "数据验收日志.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(日志))
say("  结果已存到 output\\数据验收结果.json —— 把这个文件发给 Claude")
