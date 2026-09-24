# -*- coding: utf-8 -*-
"""
WRDS 数据可用性自检
===================
在写任何分析代码之前，先回答一个问题：
「我要的三样东西，在我有权限的库里真的存在、且真的有值吗？」

要验的三样：
  1. CRSP 的退市收益（dlret）—— 没有它，美股回测就有幸存者偏差，
     和你在 A 股费力保留 337 只退市股是一个道理
  2. Compustat 的报告日期（rdq）—— 这是美股版的 PIT 锚点，
     对应你在 A 股发现的「ann_date 延迟 396 天」那个问题
  3. CCM 链接表 —— 把 CRSP 的 permno 和 Compustat 的 gvkey 连起来

⚠️ 数据合规：WRDS 的数据不可再分发。
   这个脚本只打印统计量和极小的样本用于核对，不落盘任何原始数据。
   正式拉数时，原始文件一律放在 .gitignore 覆盖的目录里。
"""

# ----------------------------------------------------------------------
# LICENCE NOTE -- read before changing this file.
#
# CRSP and Compustat are licensed through an institutional (university)
# subscription. The licence permits use for research; it does NOT permit
# redistribution of the data. A breach does not stay personal -- it can
# suspend an entire university's access.
#
# Rules this file follows, and that any change must preserve:
#   * It NEVER writes query results to disk. It connects, queries, prints.
#     If you need to save an extract, save it under data/us/ or
#     data/wrds/, both of which are excluded in .gitignore.
#   * Credentials come ONLY from the environment (WRDS_USER / WRDS_PASS)
#     or an interactive prompt. Never hard-code them, never log them,
#     never write them to a config file in this repository.
#   * WRDS accounts are personal and non-transferable. Sharing the
#     username or password forfeits the account.
# ----------------------------------------------------------------------

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from wrds_conn import 连接
except ImportError as e:
    print(f"找不到 wrds_conn.py（{e}）")
    print("请确认 code\\wrds_conn.py 存在。")
    sys.exit(1)

import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)


def bar(ch="-"):
    print(ch * 70)


def 主():
    print()
    db = 连接()
    print()

    # ---------- 0. 我有权限的库 ----------
    bar("=")
    print("  第 0 项  我能访问哪些库")
    bar("=")
    try:
        libs = db.列出库()
        关注 = [x for x in libs if any(k in x for k in ("crsp", "comp", "ff", "ibes"))]
        print(f"  共 {len(libs)} 个 schema，其中和本项目相关的（前20）：")
        print(f"    {关注[:20]}")
        for 必需, 说明 in (("crsp", "价格/退市"), ("comp", "财务/报告日")):
            有 = any(x == 必需 or x.startswith(必需) for x in libs)
            print(f"    {'✓' if 有 else '✗ 看不到！'}  {必需:<6}（{说明}）")
    except Exception as e:
        print(f"  列库失败：{e}")
    print()

    # ---------- 1. CRSP 退市收益 ----------
    bar("=")
    print("  第 1 项  CRSP 退市收益 —— 幸存者偏差的解药")
    bar("=")
    try:
        df = db.查询("""
            SELECT permno, dlstdt, dlstcd, dlret
            FROM crsp.msedelist
            WHERE dlstdt BETWEEN '2000-01-01' AND '2024-12-31'
        """)
        print(f"  msedelist 退市记录：{len(df):,} 条（2000–2024）")
        有值 = df["dlret"].notna().sum()
        print(f"    其中 dlret 有值：{有值:,} 条（{有值/max(len(df),1)*100:.1f}%）")
        print(f"    退市收益中位数：{df['dlret'].median():.4f}")
        print(f"    退市代码分布（前8）：")
        for 码, n in df["dlstcd"].value_counts().head(8).items():
            print(f"      {int(码)}  {n:>6,} 次")
        print("  ✓ 有退市收益 —— 美股回测可以做到无幸存者偏差")
    except Exception as e:
        print(f"  ✗ 取不到：{e}")
        print("    可能表名不同，去 Get Data 里搜 'delist' 确认实际表名")
    print()

    # ---------- 2. Compustat 报告日期 rdq ----------
    bar("=")
    print("  第 2 项  Compustat 的 rdq —— 美股版 PIT 锚点")
    bar("=")
    try:
        df = db.查询("""
            SELECT gvkey, datadate, rdq, fqtr, fyearq, epsfxq, atq
            FROM comp.fundq
            WHERE datadate BETWEEN '2020-01-01' AND '2023-12-31'
              AND indfmt='INDL' AND datafmt='STD'
              AND popsrc='D' AND consol='C'
            LIMIT 200000
        """)
        print(f"  fundq 样本：{len(df):,} 条（2020–2023）")
        有rdq = df["rdq"].notna().sum()
        print(f"    rdq 有值：{有rdq:,} 条（{有rdq/max(len(df),1)*100:.1f}%）")
        d = df.dropna(subset=["rdq", "datadate"]).copy()
        d["延迟"] = (pd.to_datetime(d["rdq"]) - pd.to_datetime(d["datadate"])).dt.days
        print(f"    报告延迟（rdq − datadate）：")
        for p in (5, 25, 50, 75, 95):
            print(f"      {p:>2}% 分位  {d['延迟'].quantile(p/100):>6.0f} 天")
        提前 = int((d["延迟"] < 0).sum())
        print(f"    rdq 早于报告期末（未来函数）：{提前} 条  "
              f"{'✓ 干净' if 提前 == 0 else '← 需要人工看'}")
        print()
        print("  ★ 对比你在 A 股的发现：")
        print("     A 股 ann_date 中位延迟 396 天（因为是「最新公告日期」不是首次披露日）")
        print(f"     美股 rdq  中位延迟 {d['延迟'].median():.0f} 天")
        print("     → 这个对比本身就是 research note 里一张值钱的表")
    except Exception as e:
        print(f"  ✗ 取不到：{e}")
    print()

    # ---------- 3. CCM 链接表 ----------
    bar("=")
    print("  第 3 项  CCM 链接表 —— 把两边连起来")
    bar("=")
    for 表 in ("crsp.ccmxpf_lnkhist", "crsp.ccmxpf_linktable",
               "crsp_a_ccm.ccmxpf_lnkhist", "crsp.ccmxpf_lnkused"):
        try:
            df = db.查询(f"SELECT * FROM {表} LIMIT 5")
            print(f"  ✓ {表} 可用，字段：{list(df.columns)}")
            break
        except Exception:
            print(f"  · {表} 不可用，试下一个")
    print()

    # ---------- 4. 样本规模估算 ----------
    bar("=")
    print("  第 4 项  样本规模（决定这章能做多硬）")
    bar("=")
    try:
        df = db.查询("""
            SELECT EXTRACT(YEAR FROM date) AS yr,
                   COUNT(DISTINCT permno) AS n
            FROM crsp.msf
            WHERE date BETWEEN '2011-01-01' AND '2025-12-31'
            GROUP BY 1 ORDER BY 1
        """)
        print(f"  {'年份':<8}{'月频样本中的股票数':>18}")
        for _, r in df.iterrows():
            print(f"  {int(r['yr']):<8}{int(r['n']):>18,}")
        print()
        print(f"  对照：你的 A 股库是 5,492 只 × 15.5 年")
    except Exception as e:
        print(f"  ✗ 取不到：{e}")
    print()

    bar("=")
    print("  自检完成。把这段输出发给 Claude，据此定美股那一章怎么做。")
    print()
    print("  ⚠️ 提醒：以上任何数据都不要提交到公开仓库。")
    print("     WRDS 许可禁止再分发，违反可能影响哥大整个订阅。")
    bar("=")
    db.关闭()


if __name__ == "__main__":
    try:
        主()
    except KeyboardInterrupt:
        print("\n已中断。")
    except Exception:
        import traceback
        traceback.print_exc()
    if not os.environ.get("XUANGU_NO_PAUSE"):
        input("\n按回车关闭。")
