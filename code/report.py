# -*- coding: utf-8 -*-
"""
回测报告生成器 —— 纯内联 SVG，不依赖任何外部资源，离线可看
============================================================
配色取自已验证的分类调色板（三序列全配对模式、明暗双模式均 PASS）。
浅色下 aqua 对比度 2.74:1 触发 relief 规则，故线端一律直标 + 全部数字另有表格。

涨跌沿用 A 股惯例：红涨绿跌（与西方相反），这是本主题自己的语言。
"""

import os, json, html
import numpy as np
import pandas as pd

# 分类序列（身份），验证通过：worst all-pairs CVD ΔE 9.2 light / 9.4 dark
序列色 = {
    "策略": ("#2a78d6", "#3987e5"),
    "沪深300": ("#eb6834", "#d95926"),
    "中证红利": ("#1baf7a", "#199e70"),
    "中证500": ("#eda100", "#c98500"),
}


def esc(x):
    return html.escape(str(x))


def pct(v, 位=2):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    return f"{v*100:.{位}f}%"


# ============================================================
# SVG 基础
# ============================================================
def _刻度(lo, hi, n=5):
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return [lo, hi]
    步 = (hi - lo) / n
    幂 = 10 ** math_floor_log10(步)
    for m in (1, 2, 2.5, 5, 10):
        if 步 <= 幂 * m:
            步 = 幂 * m
            break
    起 = np.floor(lo / 步) * 步
    out = []
    v = 起
    while v <= hi + 步 * .5:
        if v >= lo - 步 * .5:
            out.append(round(v, 10))
        v += 步
    return out


def math_floor_log10(x):
    return int(np.floor(np.log10(x))) if x > 0 else 0


def 净值图(净值表, 高=300):
    """多序列折线，全部归一化到 1。线端直标 + 图例（relief 规则）。"""
    W, H = 900, 高
    L, R, T, B = 56, 112, 16, 34
    pw, ph = W - L - R, H - T - B

    df = 净值表.dropna(how="all")
    归一 = df / df.iloc[0]
    xs = list(range(len(归一)))
    lo = float(np.nanmin(归一.values)) * .97
    hi = float(np.nanmax(归一.values)) * 1.03

    def X(k):
        return L + pw * k / max(len(xs) - 1, 1)

    def Y(v):
        return T + ph * (1 - (v - lo) / (hi - lo))

    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" '
         f'style="display:block;overflow:visible" role="img" '
         f'aria-label="净值曲线">']
    # 网格
    for t in _刻度(lo, hi):
        y = Y(t)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+pw}" y2="{y:.1f}" '
                 f'stroke="var(--grid)" stroke-width="1"/>')
        s.append(f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" '
                 f'font-size="11" fill="var(--ink-3)" '
                 f'style="font-variant-numeric:tabular-nums">{t:.2f}</text>')
    # x 轴年份
    年 = pd.Series(归一.index).dt.year
    见过 = set()
    for k, y_ in enumerate(年):
        if y_ not in 见过 and (y_ % 2 == 0 or k == 0):
            见过.add(y_)
            s.append(f'<text x="{X(k):.1f}" y="{T+ph+20}" text-anchor="middle" '
                     f'font-size="11" fill="var(--ink-3)">{y_}</text>')
    # 线
    for 名 in 归一.columns:
        c = 序列色.get(名, ("#6C7585", "#818B9C"))[0]
        vals = 归一[名].values
        pts = " ".join(f"{X(k):.1f},{Y(v):.1f}"
                       for k, v in enumerate(vals) if np.isfinite(v))
        宽 = 2.4 if 名 == "策略" else 1.6
        s.append(f'<polyline points="{pts}" fill="none" '
                 f'stroke="{c}" stroke-width="{宽}" '
                 f'stroke-linejoin="round" stroke-linecap="round" '
                 f'class="ln" data-name="{esc(名)}"/>')
        末 = vals[-1]
        if np.isfinite(末):
            s.append(f'<circle cx="{X(len(vals)-1):.1f}" cy="{Y(末):.1f}" '
                     f'r="3.5" fill="{c}" stroke="var(--surface)" '
                     f'stroke-width="2"/>')
            # 线端直标（relief：不靠颜色识别身份）
            s.append(f'<text x="{X(len(vals)-1)+9:.1f}" y="{Y(末)+4:.1f}" '
                     f'font-size="11.5" font-weight="600" fill="{c}" '
                     f'style="font-variant-numeric:tabular-nums">'
                     f'{esc(名)} {末:.2f}</text>')
    s.append("</svg>")
    return "".join(s)


def 回撤图(nv, 高=140):
    W, H = 900, 高
    L, R, T, B = 56, 112, 10, 26
    pw, ph = W - L - R, H - T - B
    dd = (nv / nv.cummax() - 1).values
    lo = float(np.nanmin(dd)) * 1.05 if np.isfinite(np.nanmin(dd)) else -0.1
    lo = min(lo, -0.02)

    def X(k):
        return L + pw * k / max(len(dd) - 1, 1)

    def Y(v):
        return T + ph * (v / lo)

    pts = " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in enumerate(dd)
                   if np.isfinite(v))
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block" '
         f'role="img" aria-label="回撤曲线">']
    for t in (0, lo / 2, lo):
        y = Y(t)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+pw}" y2="{y:.1f}" '
                 f'stroke="var(--grid)" stroke-width="1"/>')
        s.append(f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" '
                 f'font-size="11" fill="var(--ink-3)" '
                 f'style="font-variant-numeric:tabular-nums">'
                 f'{t*100:.0f}%</text>')
    s.append(f'<polygon points="{X(0):.1f},{Y(0):.1f} {pts} '
             f'{X(len(dd)-1):.1f},{Y(0):.1f}" fill="var(--dd-fill)"/>')
    s.append(f'<polyline points="{pts}" fill="none" stroke="var(--dd-line)" '
             f'stroke-width="1.6"/>')
    最深 = int(np.nanargmin(dd))
    s.append(f'<circle cx="{X(最深):.1f}" cy="{Y(dd[最深]):.1f}" r="3.5" '
             f'fill="var(--dd-line)" stroke="var(--surface)" stroke-width="2"/>')
    s.append(f'<text x="{X(最深)+8:.1f}" y="{Y(dd[最深])+4:.1f}" font-size="11.5" '
             f'font-weight="600" fill="var(--dd-line)" '
             f'style="font-variant-numeric:tabular-nums">'
             f'最深 {dd[最深]*100:.1f}%</text>')
    s.append("</svg>")
    return "".join(s)


def 年度图(分年度, 高=230):
    if not 分年度:
        return "<p>没有分年度数据</p>"
    年 = list(分年度.keys())
    v = [分年度[k] for k in 年]
    W, H = 900, 高
    L, R, T, B = 56, 20, 18, 42
    pw, ph = W - L - R, H - T - B
    hi = max(max(v), 0.02) * 1.15
    lo = min(min(v), -0.02) * 1.15
    宽 = pw / len(年) * 0.62

    def X(k):
        return L + pw * (k + .5) / len(年)

    def Y(x):
        return T + ph * (hi - x) / (hi - lo)

    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block" '
         f'role="img" aria-label="分年度收益">']
    for t in _刻度(lo, hi, 4):
        y = Y(t)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+pw}" y2="{y:.1f}" '
                 f'stroke="var(--grid)" stroke-width="1"/>')
        s.append(f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" '
                 f'font-size="11" fill="var(--ink-3)" '
                 f'style="font-variant-numeric:tabular-nums">'
                 f'{t*100:.0f}%</text>')
    y0 = Y(0)
    s.append(f'<line x1="{L}" y1="{y0:.1f}" x2="{L+pw}" y2="{y0:.1f}" '
             f'stroke="var(--rule-strong)" stroke-width="1.4"/>')
    for k, (yr, x) in enumerate(zip(年, v)):
        # A 股惯例：红涨绿跌
        c = "var(--up)" if x >= 0 else "var(--down)"
        top = Y(max(x, 0))
        h = abs(Y(x) - y0)
        s.append(f'<rect x="{X(k)-宽/2:.1f}" y="{top:.1f}" width="{宽:.1f}" '
                 f'height="{max(h,1):.1f}" fill="{c}" rx="3"/>')
        s.append(f'<text x="{X(k):.1f}" y="{T+ph+18}" text-anchor="middle" '
                 f'font-size="10.5" fill="var(--ink-3)">{yr}</text>')
        ly = top - 6 if x >= 0 else Y(x) + 14
        s.append(f'<text x="{X(k):.1f}" y="{ly:.1f}" text-anchor="middle" '
                 f'font-size="10.5" font-weight="600" fill="{c}" '
                 f'style="font-variant-numeric:tabular-nums">'
                 f'{x*100:.0f}%</text>')
    s.append("</svg>")
    return "".join(s)


def 运气图(分布, 实际, 分位, 高=200):
    """随机选股的年化分布，和实际结果的位置。小资金最该看的一张图。"""
    if not 分布:
        return ""
    ks = ["5%", "25%", "50%", "75%", "95%"]
    vs = [分布[k] for k in ks]
    W, H = 900, 高
    L, R, T, B = 56, 20, 26, 46
    pw, ph = W - L - R, H - T - B
    lo = min(min(vs), 实际) * 1.15 if min(min(vs), 实际) < 0 else -0.02
    hi = max(max(vs), 实际) * 1.15

    def X(x):
        return L + pw * (x - lo) / (hi - lo)

    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block;'
         f'overflow:visible" role="img" aria-label="运气分布">']
    mid = T + ph * .45
    # 5%-95% 区间条
    s.append(f'<rect x="{X(vs[0]):.1f}" y="{mid-26:.1f}" '
             f'width="{X(vs[4])-X(vs[0]):.1f}" height="52" '
             f'fill="var(--band-wide)" rx="4"/>')
    # 25%-75%
    s.append(f'<rect x="{X(vs[1]):.1f}" y="{mid-26:.1f}" '
             f'width="{X(vs[3])-X(vs[1]):.1f}" height="52" '
             f'fill="var(--band-narrow)" rx="4"/>')
    # 中位
    s.append(f'<line x1="{X(vs[2]):.1f}" y1="{mid-30:.1f}" '
             f'x2="{X(vs[2]):.1f}" y2="{mid+30:.1f}" '
             f'stroke="var(--ink-2)" stroke-width="2"/>')
    s.append(f'<text x="{X(vs[2]):.1f}" y="{mid-38:.1f}" text-anchor="middle" '
             f'font-size="11" fill="var(--ink-2)" '
             f'style="font-variant-numeric:tabular-nums">'
             f'随机中位 {vs[2]*100:.1f}%</text>')
    # 实际
    xa = X(实际)
    s.append(f'<line x1="{xa:.1f}" y1="{mid-40:.1f}" x2="{xa:.1f}" '
             f'y2="{mid+40:.1f}" stroke="var(--accent)" stroke-width="2.5"/>')
    s.append(f'<circle cx="{xa:.1f}" cy="{mid:.1f}" r="5" '
             f'fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>')
    s.append(f'<text x="{xa:.1f}" y="{mid+58:.1f}" text-anchor="middle" '
             f'font-size="12" font-weight="700" fill="var(--accent)" '
             f'style="font-variant-numeric:tabular-nums">'
             f'按分数选股 {实际*100:.1f}%（{分位:.0%} 分位）</text>')
    # 轴
    for t in _刻度(lo, hi, 5):
        s.append(f'<text x="{X(t):.1f}" y="{T+ph+24}" text-anchor="middle" '
                 f'font-size="11" fill="var(--ink-3)" '
                 f'style="font-variant-numeric:tabular-nums">'
                 f'{t*100:.0f}%</text>')
    s.append(f'<text x="{L}" y="{T-8}" font-size="11" fill="var(--ink-3)">'
             f'← 同样规则、随机选股跑出来的年化分布（深色=中间50%，浅色=90%区间）</text>')
    s.append("</svg>")
    return "".join(s)


# ============================================================
CSS = """
.warn-box{background:#fdf2e3;border-left:4px solid #d98324;
padding:12px 14px;border-radius:0 8px 8px 0;line-height:1.7;margin:10px 0 16px;
color:#6b4208}

:root{--paper:#F6F7F9;--surface:#fff;--sunk:#EDEFF3;--ink:#171B22;
--ink-2:#434B59;--ink-3:#6C7585;--rule:#DCE0E7;--rule-strong:#BFC6D1;
--accent:#2C3E63;--accent-soft:#E7EBF3;--up:#C2392F;--down:#0F6E58;
--caution:#8A6008;--caution-bg:#FBF3DF;--crit-bg:#FBEDEB;--grid:#E8EBF0;
--dd-fill:rgba(194,57,47,.13);--dd-line:#C2392F;
--band-wide:rgba(44,62,99,.10);--band-narrow:rgba(44,62,99,.22);}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
--paper:#0F1218;--surface:#171B23;--sunk:#1E242E;--ink:#E6E9EF;
--ink-2:#B3BBC9;--ink-3:#818B9C;--rule:#2A3140;--rule-strong:#3B4456;
--accent:#8FA8D8;--accent-soft:#1D2533;--up:#E8695C;--down:#3FB394;
--caution:#D9AC4A;--caution-bg:#2A2314;--crit-bg:#2C1B19;--grid:#242B37;
--dd-fill:rgba(232,105,92,.16);--dd-line:#E8695C;
--band-wide:rgba(143,168,216,.13);--band-narrow:rgba(143,168,216,.28);}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.8 "Noto Sans SC","PingFang SC","Microsoft YaHei",-apple-system,sans-serif}
.w{max-width:940px;margin:0 auto;padding:0 20px 80px}
header{border-bottom:2px solid var(--ink);padding:40px 0 18px;margin-bottom:6px}
h1{font-size:29px;margin:0 0 8px;font-weight:700;letter-spacing:-.01em}
.sub{color:var(--ink-3);font-size:12.5px;
font-family:ui-monospace,Consolas,monospace}
h2{font-size:20px;margin:46px 0 6px;padding-bottom:9px;
border-bottom:1px solid var(--ink);display:flex;gap:14px;align-items:baseline}
h2 .n{font-family:ui-monospace,Consolas,monospace;font-size:12px;
color:var(--accent);font-weight:600}
h3{font-size:15.5px;margin:30px 0 8px;font-weight:700}
p{margin:0 0 14px}
.verdict{padding:20px 22px;border:1px solid var(--rule);border-left:4px solid var(--accent);
background:var(--surface);border-radius:3px;margin:22px 0}
.verdict.good{border-left-color:var(--down)}
.verdict.bad{border-left-color:var(--up)}
.verdict h3{margin:0 0 8px;font-size:17px}
.verdict p{margin:0;color:var(--ink-2);font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:1px;background:var(--rule);border:1px solid var(--rule);border-radius:3px;
overflow:hidden;margin:22px 0}
.tile{background:var(--surface);padding:15px 17px}
.tile b{display:block;font-family:ui-monospace,Consolas,monospace;font-size:10px;
letter-spacing:.11em;text-transform:uppercase;color:var(--ink-3);
font-weight:500;margin-bottom:5px}
.tile .v{font-size:23px;font-weight:700;letter-spacing:-.02em;
font-variant-numeric:tabular-nums;line-height:1.25}
.tile .s{font-size:11.5px;color:var(--ink-3);margin-top:2px}
.up{color:var(--up)}.down{color:var(--down)}
.chart{background:var(--surface);border:1px solid var(--rule);border-radius:3px;
padding:18px 16px 12px;margin:20px 0}
.chart .cap{font-size:12px;color:var(--ink-3);margin:0 0 12px;
padding-left:2px;line-height:1.6}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0 0;padding-left:2px;
font-size:12.5px;color:var(--ink-2)}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;
margin-right:6px;vertical-align:middle}
.tw{overflow-x:auto;border:1px solid var(--rule);border-radius:3px;
background:var(--surface);margin:18px 0}
table{border-collapse:collapse;width:100%;min-width:560px;font-size:13.5px}
th,td{padding:9px 13px;text-align:left;border-bottom:1px solid var(--rule);
vertical-align:top;line-height:1.55}
th{background:var(--sunk);font-size:11px;letter-spacing:.06em;
color:var(--ink-2);font-weight:700;white-space:nowrap}
tr:last-child td{border-bottom:0}
td.n,th.n{font-family:ui-monospace,Consolas,monospace;text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;font-family:ui-monospace,Consolas,monospace;
font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:2px;white-space:nowrap}
.pill.y{background:rgba(15,110,88,.14);color:var(--down)}
.pill.n{background:rgba(194,57,47,.14);color:var(--up)}
.pill.o{background:rgba(138,96,8,.17);color:var(--caution)}
.note{background:var(--caution-bg);border-left:3px solid var(--caution);
padding:15px 18px;margin:20px 0;font-size:14px;border-radius:2px;line-height:1.75}
.note.crit{background:var(--crit-bg);border-left-color:var(--up)}
.note b{font-weight:700}
footer{margin-top:64px;padding-top:20px;border-top:2px solid var(--ink);
font-size:12.5px;color:var(--ink-3);line-height:1.8}
.disc{background:var(--sunk);border-radius:3px;padding:16px 18px;
font-size:12.5px;color:var(--ink-2);line-height:1.75}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""


def 生成(R, 净值表, out_dir):
    全 = R.get("全程", {})
    外 = R.get("样本外", {})
    验 = R.get("验收", {})
    运 = R.get("运气分布", {})
    调 = R.get("调仓记录", [])
    cfg = R.get("配置", {})
    nv = 净值表["策略"].dropna()

    b = []

    # ---------- 结论 ----------
    通过, 总 = 验.get("通过数", 0), 验.get("总数", 0)
    if 验.get("全部通过"):
        b.append(f'<div class="verdict good"><h3>✓ {通过}/{总} 条验收标准全部达标</h3>'
                 '<p>这套规则在扣除全部真实成本、且包含已退市股票的前提下，'
                 '通过了开工前约定的每一条标准。但请继续读完"运气占比"那一节——'
                 '以小资金能持有的只数，结果里有相当一部分由运气决定。</p></div>')
    else:
        未过 = [x["项"] for x in 验.get("逐条", [])
                if x.get("达标") is False]
        b.append(f'<div class="verdict bad"><h3>✗ {通过}/{总} 条达标，'
                 f'{总-通过} 条未达标</h3>'
                 f'<p>未达标：<b>{esc("、".join(未过))}</b>。'
                 '按开工前的约定，这种情况如实报告，不调参数把它凑及格。'
                 '下面每一条都列出了实际值与要求值。</p></div>')

    # ---------- 核心指标 ----------
    def tile(名, 值, 副="", 色=""):
        return (f'<div class="tile"><b>{esc(名)}</b>'
                f'<div class="v {色}">{值}</div>'
                f'<div class="s">{esc(副)}</div></div>')

    年化 = 全.get("年化")
    b.append('<div class="tiles">')
    b.append(tile("年化收益", pct(年化),
                  f"全程 {全.get('年数','—')} 年",
                  "up" if (年化 or 0) > 0 else "down"))
    b.append(tile("最大回撤", pct(全.get("最大回撤")),
                  f"沪深300 同期 {pct(全.get('基准最大回撤'))}", "down"))
    b.append(tile("Calmar", 全.get("Calmar") or "—", "年化 ÷ 最大回撤"))
    b.append(tile("夏普", 全.get("夏普") or "—", "日频年化"))
    b.append(tile("最差连续12个月", pct(全.get("最差连续12个月")),
                  "历史上最难熬的一年", "down"))
    b.append(tile("月胜率", pct(全.get("月胜率"), 1), "上涨月份占比"))
    b.append('</div>')

    # ---------- 净值 ----------
    b.append('<h2><span class="n">01</span>净值曲线</h2>')
    b.append('<div class="chart">'
             '<p class="cap">全部归一化到 1。策略曲线已扣除佣金（含单笔最低5元）、'
             '印花税、过户费与滑点；基准为价格指数，不含股息再投。</p>')
    b.append(净值图(净值表))
    b.append('<div class="legend">')
    for 名 in 净值表.columns:
        c = 序列色.get(名, ("#6C7585",))[0]
        b.append(f'<span><i style="background:{c}"></i>{esc(名)}</span>')
    b.append('</div></div>')

    b.append('<div class="chart"><p class="cap">回撤（当前净值相对历史最高点）。'
             '这条线比收益曲线更值得看——它决定你拿不拿得住。</p>')
    b.append(回撤图(nv))
    b.append('</div>')

    # ---------- 分年度 ----------
    b.append('<h2><span class="n">02</span>分年度收益</h2>')
    b.append('<div class="chart"><p class="cap">按 A 股惯例红涨绿跌。'
             '注意亏损年份——任何策略都有，提前知道才拿得住。</p>')
    b.append(年度图(全.get("分年度", {})))
    b.append('</div>')

    # ---------- 验收 ----------
    b.append('<h2><span class="n">03</span>验收标准逐条核对</h2>')
    b.append('<p>这六条是开工前就定死的，不是看到结果后补写的。</p>')
    b.append('<div class="tw"><table><thead><tr><th>验收项</th><th>结果</th>'
             '<th>实际</th><th>要求</th></tr></thead><tbody>')
    for x in 验.get("逐条", []):
        if x.get("达标") is True:
            p = '<span class="pill y">达标</span>'
        elif x.get("达标") is False:
            p = '<span class="pill n">未达标</span>'
        else:
            p = '<span class="pill o">如实告知</span>'
        b.append(f'<tr><td><b>{esc(x["项"])}</b></td><td>{p}</td>'
                 f'<td class="n">{esc(x["实际"])}</td>'
                 f'<td>{esc(x["要求"])}</td></tr>')
    b.append('</tbody></table></div>')

    # ---------- 样本外 ----------
    b.append('<h2><span class="n">04</span>样本外检验</h2>')
    b.append(f'<p>最后 {cfg.get("样本外年数", 3)} 年完全不参与任何设计决策。'
             '如果样本外明显差于全程，说明前面的结果是拟合出来的。</p>')
    b.append('<div class="tw"><table><thead><tr><th>区间</th>'
             '<th class="n">年化</th><th class="n">最大回撤</th>'
             '<th class="n">Calmar</th><th class="n">夏普</th>'
             '</tr></thead><tbody>')
    for 名, m in (("全程", 全), ("样本外", 外)):
        b.append(f'<tr><td><b>{名}</b> {esc(m.get("起","—"))} ~ '
                 f'{esc(m.get("止","—"))}</td>'
                 f'<td class="n">{pct(m.get("年化"))}</td>'
                 f'<td class="n">{pct(m.get("最大回撤"))}</td>'
                 f'<td class="n">{m.get("Calmar") or "—"}</td>'
                 f'<td class="n">{m.get("夏普") or "—"}</td></tr>')
    b.append('</tbody></table></div>')

    # ---------- 运气 ----------
    if 运:
        b.append('<h2><span class="n">05</span>多少是本事，多少是运气</h2>')
        b.append(f'<p>用同一套规则，但每期从合格池里<b>随机</b>取同样只数，'
                 f'重跑 {运.get("样本数", 0)} 次。如果按分数选股的结果落在随机分布的中间，'
                 '说明排序没带来真实优势。</p>')
        b.append('<div class="chart"><p class="cap">随机选股的年化分布 vs 实际结果</p>')
        b.append(运气图(运.get("分布", {}), 全.get("年化", 0),
                        运.get("实际分位", 0)))
        b.append('</div>')
        分 = 运.get("分布", {})
        b.append('<div class="tw"><table><thead><tr><th>分位</th>'
                 + "".join(f'<th class="n">{k}</th>' for k in 分)
                 + '</tr></thead><tbody><tr><td>随机选股年化</td>'
                 + "".join(f'<td class="n">{pct(v)}</td>' for v in 分.values())
                 + '</tr></tbody></table></div>')
        位 = 运.get("实际分位", 0)
        if 位 < 0.80:
            b.append('<div class="note crit"><b>这一节比收益数字更重要。</b><br>'
                     f'实际结果只位于随机分布的 {位:.0%} 分位，'
                     '意味着这个年化里很大一部分不是选股能力，是运气。'
                     '这是小资金只能持有少数几只股票的必然代价，不是模型坏了。<br><br>'
                     '实用含义：赚了不代表方法对，亏了不代表方法错。'
                     '判断这套规则好不好，要看它连续执行多年后的结果，'
                     '而不是某一年的盈亏。</div>')
        else:
            b.append(f'<div class="note"><b>排序确实带来了优势。</b>'
                     f'实际结果位于随机分布的 {位:.0%} 分位，'
                     '说明按因子分数选股比随机选优。但请注意，'
                     '这仍不排除单年结果的大幅波动。</div>')

    # ---------- 熔断对比 ----------
    对比 = R.get("熔断对比", {})
    if len(对比) > 1:
        b.append('<h2><span class="n">06</span>要不要加回撤熔断</h2>')
        b.append('<p>你要求两种都跑、用数据说话。下面是结果。</p>')
        b.append('<div class="tw"><table><thead><tr><th>风控口径</th>'
                 '<th class="n">年化</th><th class="n">最大回撤</th>'
                 '<th class="n">Calmar</th><th class="n">最差连续12个月</th>'
                 '</tr></thead><tbody>')
        for 名, m in 对比.items():
            b.append(f'<tr><td><b>{esc(名)}</b></td>'
                     f'<td class="n">{pct(m.get("年化"))}</td>'
                     f'<td class="n">{pct(m.get("最大回撤"))}</td>'
                     f'<td class="n">{m.get("Calmar") or "—"}</td>'
                     f'<td class="n">{pct(m.get("最差连续12个月"))}</td></tr>')
        b.append('</tbody></table></div>')

    # ---------- 最新持仓 ----------
    最新 = None
    for r in reversed(调):
        if r.get("持仓"):
            最新 = r
            break
    if 最新:
        b.append('<h2><span class="n">07</span>回测最后一期的持仓（<b>不是给你的下单清单</b>）</h2>')
        _资 = float(最新.get("总资产") or 0)
        _初 = float((cfg or {}).get("初始资金") or 0)
        b.append(
            '<p class="warn-box"><b>先看清楚这一段再往下看表。</b><br>'
            f'下面这张表是回测跑到 <b>{esc(最新["日期"])}</b> 时，'
            f'那个<b>虚拟账户</b>的持仓。那个账户从 {_初:,.0f} 元起步，'
            f'到这一天已经滚到 <b>{_资:,.0f} 元</b>，所以它能持 '
            f'{最新["目标持仓数"]} 只。<br>'
            f'<b>这不等于你现在的钱能买这些。</b>如果你现在只有 {_初:,.0f} 元，'
            f'这 {len(最新.get("持仓", []))} 只光买一手就要 '
            f'{sum(float(h.get("一手金额") or 0) for h in 最新.get("持仓", [])):,.0f} 元。<br>'
            f'要看「按<b>你自己</b>现在的资金，今天该买什么」，'
            f'请在控制台点「今日选股」，或双击 06_今日选股.bat。</p>')
        b.append(f'<p>该调仓日合格标的 {最新["合格数"]} 只，'
                 f'虚拟账户总资产 {_资:,.0f} 元，目标持仓 {最新["目标持仓数"]} 只。'
                 + ('<b>其中部分是按综合分补足的，未通过全部门槛</b>。'
                    if 最新.get("是否补足") else "") + '</p>')
        b.append('<div class="tw"><table><thead><tr><th>代码</th><th>名称</th>'
                 '<th class="n">权重</th><th class="n">现价</th>'
                 '<th class="n">一手金额</th><th class="n">股息率</th>'
                 '<th class="n">ROE</th><th class="n">年化波动</th>'
                 '<th>行业</th></tr></thead><tbody>')
        for h in 最新["持仓"]:
            b.append(f'<tr><td class="n">{esc(h["代码"])}</td>'
                     f'<td><b>{esc(h["名称"])}</b></td>'
                     f'<td class="n">{h["权重"]*100:.1f}%</td>'
                     f'<td class="n">{h["真实价"]}</td>'
                     f'<td class="n">{h["一手金额"]:.0f}</td>'
                     f'<td class="n">{h["股息率%"] if h["股息率%"] is not None else "—"}%</td>'
                     f'<td class="n">{h["ROE%"] if h["ROE%"] is not None else "—"}%</td>'
                     f'<td class="n">{h["年化波动%"]}%</td>'
                     f'<td>{esc(h["行业"])}</td></tr>')
        b.append('</tbody></table></div>')
        b.append('<div class="note">这不是推荐买入，是这套规则在该日期的机械输出。'
                 '是否执行、执行多少，由你自己决定。</div>')

    # ---------- 成本与持仓数 ----------
    if 调:
        df = pd.DataFrame(调)
        总买 = df["买入成本"].sum()
        总卖 = df["卖出成本"].sum()
        期末 = nv.iloc[-1]
        b.append('<h2><span class="n">08</span>成本与持仓数</h2>')
        b.append('<div class="tiles">')
        b.append(tile("累计交易成本", f"{总买+总卖:,.0f} 元",
                      f"买 {总买:,.0f} / 卖 {总卖:,.0f}"))
        b.append(tile("成本占期末净值",
                      f"{(总买+总卖)/max(期末,1)*100:.1f}%",
                      "越低越好"))
        b.append(tile("平均持仓数", f"{df['实际持仓数'].mean():.1f}",
                      f"{df['实际持仓数'].min()} ~ {df['实际持仓数'].max()} 只"))
        b.append(tile("补足期数占比",
                      f"{df['是否补足'].mean()*100:.0f}%",
                      "合格标的不足、按分数补齐的期数"))
        b.append('</div>')
        b.append('<div class="note">单笔佣金最低 5 元这条规则，对小资金是隐形杀手：'
                 '买 2,500 元算出来只要 0.6 元，但实际收 5 元，'
                 '等于费率从万2.5变成万20。'
                 '<b>降低调仓频率是小资金唯一能确定改善收益的手段。</b></div>')

    # ---------- 局限 ----------
    b.append('<h2><span class="n">09</span>这份回测的已知局限</h2>')
    b.append('<div class="tw"><table><thead><tr><th>局限</th><th>影响方向</th>'
             '</tr></thead><tbody>')
    for a, c in [
        ("基准是价格指数，不含股息再投。验收时按沪深300+2%、中证红利+4%估算全收益",
         "对策略不利（已做保守处理）"),
        ("成交价用当日成交均价（成交额÷成交量），不是开盘价",
         "中性，另加了 0.1% 单边滑点"),
        ("整手约束用真实均价判断，持仓收益用后复权价",
         "仅影响手数粒度，不影响收益率"),
        ("行业分类按年取快照，年内变更未反映",
         "轻微；行业变更本身很慢"),
        ("分红用预案公告日对齐，实际到账有延迟",
         "对策略略有利，幅度很小"),
        ("未考虑融资融券、打新、可转债等增强收益",
         "对策略不利"),
        ("未模拟极端流动性枯竭（如 2024 年 2 月微盘危机）下的实际冲击成本",
         "对策略有利，是本回测最乐观的假设"),
    ]:
        b.append(f'<tr><td>{esc(a)}</td><td>{esc(c)}</td></tr>')
    b.append('</tbody></table></div>')

    head = (f'<header><h1>质量红利低波 · 回测报告</h1>'
            f'<div class="sub">初始资金 {cfg.get("初始资金","—"):,} 元 · '
            f'每{cfg.get("调仓频率","—")}调仓 · '
            f'{esc(全.get("起","—"))} 至 {esc(全.get("止","—"))} · '
            f'生成于 {esc(R.get("生成时间",""))}</div></header>')

    foot = ('<footer><div class="disc"><b>重要说明。</b>'
            '本报告是历史数据的统计结果，不构成任何投资建议，'
            '不对任何证券的未来表现作出预测或承诺。历史表现不代表未来收益。'
            '回测结果依赖于所用数据的完整性与所设假设，'
            '真实交易中的滑点、流动性与执行差异可能使实际结果显著低于回测。'
            '投资有风险，决策由使用者自行承担。</div></footer>')

    html_doc = (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>回测报告 · 质量红利低波</title><style>{CSS}</style></head>'
                f'<body><div class="w">{head}{"".join(b)}{foot}</div></body></html>')

    p = os.path.join(out_dir, "回测报告.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return p
