# -*- coding: utf-8 -*-
"""
A股选股工具 — 第二步：建立本地数据库
==========================================
把历史数据一次性下载到本地 SQLite，之后所有回测都离线跑。

设计依据（来自第一步的体检结果）：
  · Baostock 7/7 全部通过 → 作为主数据源
  · AKShare 4/8，失败全是连接层抖动 → 只用它做不可替代的那一项，且必须重试
  · 幸存者偏差：用 Baostock 的历史股票列表 + outDate，把退市股也收进来

特性：
  · 断点续传 —— 中途关掉，下次双击接着跑
  · 每个网络调用都有重试 + 退避
  · 两种模式：试运行(约10分钟) / 全量(数小时)

作者: Claude  |  版本: 1.0
"""

import sys, os, json, time, sqlite3, warnings, traceback, shutil
import multiprocessing as mp
from datetime import datetime, date

warnings.filterwarnings("ignore")

# ---- 诊断实测得出的常量（见 output/诊断结果.json） ----
并发进程数 = 4          # 实测 4 进程 4.2s/只；8 进程反而 9.1s/只（服务端限流）
A股前缀 = ("60", "68", "00", "30")   # 沪市主板/科创/深市主板/创业板
                                     # 剔除 北交所(83/87/92/43)、新三板(40/42)、B股(90/20)

# ============================================================
# 配置
# ============================================================
起始日期 = "2010-01-01"
结束日期 = date.today().strftime("%Y-%m-%d")
试运行股票数 = 300

指数列表 = {
    "sh.000300": "沪深300",
    "sh.000905": "中证500",
    "sh.000906": "中证800",
    "sh.000852": "中证1000",
    "sh.000922": "中证红利",
    "sh.000001": "上证指数",
    "sz.399006": "创业板指",
}
# ============================================================

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "output")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "ashare.db")

_t_start = time.time()
日志 = []


def say(m=""):
    print(m, flush=True)
    日志.append(str(m))


def bar(c="-"):
    say(c * 64)


def 用时(s):
    s = int(s)
    if s < 60:
        return f"{s}秒"
    if s < 3600:
        return f"{s//60}分{s%60}秒"
    return f"{s//3600}小时{(s%3600)//60}分"


# ============================================================
# 数据库
# ============================================================
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS meta(
  k TEXT PRIMARY KEY, v TEXT);

-- 股票名录（含已退市，这是对抗幸存者偏差的地基）
CREATE TABLE IF NOT EXISTS stock_basic(
  code TEXT PRIMARY KEY, name TEXT, ipo_date TEXT, out_date TEXT,
  type TEXT, status TEXT);

-- 日线（后复权），含逐日 ST 标识与停牌标识
CREATE TABLE IF NOT EXISTS daily(
  code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL, turn REAL, pct_chg REAL,
  trade_status INTEGER, is_st INTEGER,
  PRIMARY KEY(code, date));
CREATE INDEX IF NOT EXISTS ix_daily_date ON daily(date);

-- 财务（业绩报表横截面，含公告日 = PIT 的关键）
CREATE TABLE IF NOT EXISTS finance(
  code TEXT, report_date TEXT, ann_date TEXT,
  eps REAL, revenue REAL, rev_yoy REAL, np REAL, np_yoy REAL,
  bps REAL, roe REAL, ocfps REAL, gpm REAL,
  PRIMARY KEY(code, report_date));
CREATE INDEX IF NOT EXISTS ix_fin_ann ON finance(ann_date);

-- 分红（列名以诊断实测为准：代码 / 现金分红-现金分红比例 = 每10股派息元 / 预案公告日）
-- 注意：接口自带的"股息率"按最新价算，有前视偏差，不入库。
--       回测时用 cash_per10 ÷ 调仓日真实价格 自己算。
CREATE TABLE IF NOT EXISTS dividend(
  code TEXT, report_date TEXT,
  plan_ann_date TEXT,      -- 预案公告日（PIT 用这个）
  latest_ann_date TEXT,    -- 最新公告日期
  cash_per10 REAL,         -- 每10股派息（元，税前）
  total_share REAL,        -- 总股本
  record_date TEXT,        -- 股权登记日
  ex_date TEXT,            -- 除权除息日
  progress TEXT,           -- 方案进度
  PRIMARY KEY(code, report_date));

-- 行业（诊断确认 Baostock 支持历史日期，故按快照日存多份）
CREATE TABLE IF NOT EXISTS industry(
  code TEXT, snapshot_date TEXT, name TEXT, industry TEXT,
  classification TEXT, update_date TEXT,
  PRIMARY KEY(code, snapshot_date));
CREATE INDEX IF NOT EXISTS ix_ind_snap ON industry(snapshot_date);

-- 指数
CREATE TABLE IF NOT EXISTS index_daily(
  code TEXT, date TEXT, close REAL, pct_chg REAL,
  PRIMARY KEY(code, date));

-- 无风险利率
CREATE TABLE IF NOT EXISTS bond_yield(
  date TEXT PRIMARY KEY, cn10y REAL);

-- 断点续传
CREATE TABLE IF NOT EXISTS progress(
  task TEXT, key TEXT, status TEXT, note TEXT, ts TEXT,
  PRIMARY KEY(task, key));
"""


def 迁移旧库(c):
    """industry / dividend 两张表结构已变更。检测到旧结构就重建。
    这两张表的数据重拉很便宜（行业约25分钟、分红约15分钟），
    而 daily / finance 这两张贵表原样保留。"""
    换掉 = []
    for 表, 必需列 in [("industry", "snapshot_date"), ("dividend", "plan_ann_date")]:
        try:
            列 = [r[1] for r in c.execute(f"PRAGMA table_info({表})")]
        except Exception:
            continue
        if 列 and 必需列 not in 列:
            换掉.append(表)
    for 表 in 换掉:
        # 索引要先删，否则 DROP TABLE 后残留索引会挡住重建
        for idx in [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                (表,)) if r[0] and not r[0].startswith("sqlite_")]:
            c.execute(f"DROP INDEX IF EXISTS {idx}")
        c.execute(f"DROP TABLE IF EXISTS {表}")
        try:
            c.execute("DELETE FROM progress WHERE task=?",
                      ("ind" if 表 == "industry" else "div",))
        except Exception:
            pass          # 全新库还没有 progress 表，正常
    if 换掉:
        c.commit()
        say(f"  已升级表结构：{'、'.join(换掉)}"
            f"（这两张表会重新拉取；daily / finance 原样保留，不会重下）")

    # 清洗已有的 finance：早先版本没过滤，把北交所/新三板/B股也存进来了
    # （诊断实测：11,506 个代码里沪深A股只有 5,226 个）
    try:
        脏 = c.execute(
            "SELECT COUNT(*) FROM finance WHERE SUBSTR(code,1,2) NOT IN "
            "('60','68','00','30')").fetchone()[0]
        if 脏:
            c.execute("DELETE FROM finance WHERE SUBSTR(code,1,2) NOT IN "
                      "('60','68','00','30')")
            剩 = c.execute("SELECT COUNT(*) FROM finance").fetchone()[0]
            c.commit()
            say(f"  已清洗 finance：删除非沪深A股 {脏:,} 条，剩 {剩:,} 条")
    except Exception:
        pass
    return 换掉


def 修复旧标记(c):
    """把「上一版代码错标成成功的空记录」改回待重下。

    上一版把 baostock 返回 0 根K线也标成了 ok，这些股票会被断点续传
    永久跳过，数据永久缺失。这里把它们挑出来改成 empty，
    下次跑就会自动重试。只改标记，不动任何已下好的数据。
    """
    try:
        c.execute("SELECT 1 FROM progress LIMIT 1")
    except Exception:
        return          # 还没有 progress 表，全新库，不用修
    try:
        条件 = ("task='daily' AND status='ok' AND "
                "(note='0根' OR note='0行' OR note LIKE '0根%')")
        坏 = c.execute(f"SELECT COUNT(*) FROM progress WHERE {条件}").fetchone()[0]
        if 坏:
            c.execute(f"UPDATE progress SET status='empty', "
                      f"note='上一版错标为成功，已改回待重下' WHERE {条件}")
            c.commit()
            say(f"  ⚠ 发现 {坏} 只股票被上一版代码错标成「下载成功」但其实是空的，")
            say(f"    已改回待重下（只改标记，不动已有数据）")

        # 另一种形态：标了 ok，但 daily 表里一行都没有
        孤 = [x[0] for x in c.execute(
            "SELECT p.key FROM progress p WHERE p.task='daily' AND p.status='ok' "
            "AND NOT EXISTS (SELECT 1 FROM daily d WHERE d.code = p.key)")]
        if 孤:
            c.executemany(
                "UPDATE progress SET status='empty', "
                "note='标记为成功但库里查无数据' WHERE task='daily' AND key=?",
                [(x,) for x in 孤])
            c.commit()
            say(f"  ⚠ 另有 {len(孤)} 只标记为成功、但 daily 表里查无数据，已改回待重下")

        if not 坏 and not 孤:
            say("  ✓ 旧标记自检：没有被错标成成功的空记录")
    except Exception as e:
        say(f"  （旧标记自检跳过，不影响建库：{e}）")


def 修复分红假失败(c):
    """把上一版错标成失败的季度分红期改回完成。

    那 14 期（20060331、20060930 … 20150331）报的都是
    TypeError: 'NoneType' object is not subscriptable —— 那是 AKShare 在
    「东财没有这期数据」时的表现，不是网络错误。季度期在 2016 年之前
    几乎没有公司做，本来就该是空的。留着 fail 会每次重跑都白试一遍。
    只处理季度期；年报期的失败一律保留，那种必须补。
    """
    try:
        c.execute("SELECT 1 FROM progress LIMIT 1")
    except Exception:
        return
    try:
        条件 = ("task='div' AND status<>'ok' AND SUBSTR(key,5,4)<>'1231' "
                "AND note LIKE '%NoneType%'")
        n = c.execute(f"SELECT COUNT(*) FROM progress WHERE {条件}").fetchone()[0]
        if n:
            c.execute(f"UPDATE progress SET status='ok', "
                      f"note='接口无该期数据（季度期，正常）' WHERE {条件}")
            c.commit()
            say(f"  ✓ {n} 个季度分红期原本被错标为失败（实为「接口无该期数据」），已改回完成")
    except Exception as e:
        say(f"  （分红标记自检跳过：{e}）")


def open_db():
    c = sqlite3.connect(DB, timeout=60)
    # 顺序要紧：必须先迁移旧结构，再建表建索引。
    # 否则 CREATE INDEX ... ON industry(snapshot_date) 会在旧表上报
    # "no such column: snapshot_date"。
    迁移旧库(c)
    c.executescript(SCHEMA)
    c.commit()
    修复旧标记(c)
    修复分红假失败(c)
    return c


def done(c, task, key):
    r = c.execute("SELECT status FROM progress WHERE task=? AND key=?",
                  (task, str(key))).fetchone()
    return r is not None and r[0] == "ok"


def mark(c, task, key, status="ok", note=""):
    c.execute("INSERT OR REPLACE INTO progress VALUES(?,?,?,?,?)",
              (task, str(key), status, str(note)[:300],
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def 失败清单(c, task):
    return [r[0] for r in c.execute(
        "SELECT key FROM progress WHERE task=? AND status!='ok'", (task,))]


# ============================================================
# 重试
# ============================================================
def 重试(fn, 次数=4, 首次等待=2.0, 名称=""):
    """网络调用统一走这里。失败退避重试，最终失败返回 (None, 错误)。"""
    wait = 首次等待
    last = None
    for i in range(次数):
        try:
            r = fn()
            return r, None
        except KeyboardInterrupt:
            raise
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if i < 次数 - 1:
                time.sleep(wait)
                wait *= 1.8
    return None, last


# ============================================================
# Baostock helpers
# ============================================================
_bs = None


def bs_login():
    global _bs
    import baostock as bs
    _bs = bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Baostock 登录失败: {lg.error_msg}")
    return bs


def bs_rows(rs):
    """把 baostock 结果集读成 list[list]，同时检查错误码"""
    if rs.error_code != "0":
        raise RuntimeError(f"baostock error {rs.error_code}: {rs.error_msg}")
    out = []
    while rs.next():
        out.append(rs.get_row_data())
    return out, rs.fields


def f(x):
    """字符串转 float，空值转 None"""
    try:
        if x is None or x == "" or x == "-":
            return None
        return float(x)
    except Exception:
        return None


def i(x):
    v = f(x)
    return None if v is None else int(v)


# ============================================================
# 任务 1：股票名录（含退市股）
# ============================================================
def 任务_股票名录(c):
    bar()
    say("任务 1 / 7  股票名录（含已退市股票）")
    bar()

    if done(c, "basic", "all"):
        n = c.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
        say(f"  已完成，跳过。名录中共 {n} 只\n")
        return

    bs = _bs
    codes = {}

    # 路线 A：一次拿全量基础信息（含已退市）
    def _a():
        return bs_rows(bs.query_stock_basic())
    r, err = 重试(_a, 名称="query_stock_basic")
    if r and len(r[0]) > 500:
        say(f"  路线A：一次性全量名录接口可用")
        rows, fields = r
        idx = {n: k for k, n in enumerate(fields)}
        for row in rows:
            code = row[idx["code"]]
            codes[code] = (code, row[idx["code_name"]], row[idx["ipoDate"]],
                           row[idx["outDate"]], row[idx["type"]], row[idx["status"]])
        say(f"  ✓ 一次性取得全量名录：{len(codes)} 条（含已退市）")
    else:
        say(f"  路线B：全量名录接口不可用（{err or '返回过少'}），改用历史快照拼接")
        say(f"        这条路会逐股补基础信息，约需 20-30 分钟，只跑一次")
        # 路线 B：逐年取历史某日的全市场列表再取并集
        年份 = list(range(int(起始日期[:4]), int(结束日期[:4]) + 1))
        见过 = set()
        for y in 年份:
            for d in (f"{y}-06-15", f"{y}-12-15"):
                if d > 结束日期:
                    continue
                rr, e2 = 重试(lambda d=d: bs_rows(bs.query_all_stock(day=d)))
                if rr:
                    for row in rr[0]:
                        见过.add(row[0])
            say(f"    {y} 年 ... 累计 {len(见过)} 只")
        say(f"  ✓ 历史并集共 {len(见过)} 只标的（含指数，稍后过滤）")
        for k, code in enumerate(sorted(见过)):
            rr, _ = 重试(lambda code=code: bs_rows(bs.query_stock_basic(code=code)), 次数=2)
            if rr and rr[0]:
                fields = rr[1]
                idx = {n: j for j, n in enumerate(fields)}
                row = rr[0][0]
                codes[code] = (code, row[idx["code_name"]], row[idx["ipoDate"]],
                               row[idx["outDate"]], row[idx["type"]], row[idx["status"]])
            if (k + 1) % 500 == 0:
                say(f"    补充基础信息 {k+1}/{len(见过)}")

    # type: 1=股票 2=指数 3=其他
    股票 = {k: v for k, v in codes.items() if v[4] == "1"}
    c.executemany("INSERT OR REPLACE INTO stock_basic VALUES(?,?,?,?,?,?)",
                  list(codes.values()))
    已退市 = sum(1 for v in 股票.values() if v[3] and str(v[3]).strip())
    mark(c, "basic", "all")
    c.commit()
    say(f"  ✓ 写入 {len(codes)} 条，其中股票 {len(股票)} 只（已退市 {已退市} 只）")
    say(f"    → 回测会包含这 {已退市} 只退市股，避免收益被系统性高估\n")


def 取股票列表(c, 限制=None):
    """沪深 A 股，含已退市（退市股必须留着，否则就是幸存者偏差）。

    过滤掉两类：
      1. 非沪深A股（北交所/B股）—— 回测端 engine.py 本来就会丢弃它们，下了也白下
      2. 在回测起点之前就已经退市的 —— 它们在窗口内一根K线都没有，
         下载必然返回空表，会把「空表=出错」这个信号搞脏
    绝不按 status 过滤 —— 那才是幸存者偏差。
    """
    全部 = c.execute(
        "SELECT code, ipo_date, out_date FROM stock_basic "
        "WHERE type='1' ORDER BY code").fetchall()

    def 是日期(x):
        x = (x or "").strip()
        return len(x) == 10 and x[4] == "-" and x[:4].isdigit() and x[:4] > "1980"

    codes, 剔板块, 剔早退 = [], 0, 0
    for code, ipo, out in 全部:
        六位 = code.split(".")[-1]
        if not 六位.startswith(A股前缀):
            剔板块 += 1
            continue
        # 只在 out_date 看起来确实是个日期、且早于回测数据起点时才剔除
        if 是日期(out) and out < 起始日期:
            剔早退 += 1
            continue
        codes.append(code)

    say(f"  股票池：{len(全部)} → {len(codes)} 只"
        f"（剔除非沪深A股 {剔板块} 只，剔除 {起始日期} 前已退市 {剔早退} 只）")
    if len(codes) < 3000:
        say(f"  ⚠ 只剩 {len(codes)} 只，明显偏少，过滤条件可能有问题，请停下来检查")
    if 限制 and len(codes) > 限制:
        step = len(codes) / 限制          # 均匀取样，沪深大小盘都覆盖到
        codes = [codes[int(k * step)] for k in range(限制)]
    return codes


# ============================================================
# 任务 2：日线行情（最耗时，可断点续传）
# ============================================================
K字段 = ("date,code,open,high,low,close,volume,amount,"
         "turn,tradestatus,pctChg,isST")


def 任务_日线(c, codes):
    bar()
    say(f"任务 2 / 7  日线行情（后复权） —— {len(codes)} 只")
    say("            这是最耗时的一步，可以随时关掉，下次接着跑")
    bar()

    bs = _bs
    待办 = [x for x in codes if not done(c, "daily", x)]
    say(f"  待下载 {len(待办)} 只（已完成 {len(codes)-len(待办)} 只）")
    if not 待办:
        say("  全部已完成，跳过\n")
        return
    say()

    say("  开始下载。每只股票要拉 16 年约 3900 根K线，需要几秒钟。")
    say("  下面每下完一只就打印一行，如果长时间不动才是真卡住了。")
    say()
    say("  提示：Windows 控制台如果被鼠标点过会进入『选择模式』并暂停程序，")
    say("        屏幕看起来像卡住。按一下 Esc 或回车就会继续。")
    say()

    # 名字先查出来，避免在收结果时反复查库
    名表 = dict(c.execute("SELECT code, name FROM stock_basic"))

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mp_fetch

    任务 = [(x, 起始日期, 结束日期) for x in 待办]
    t0 = time.time()
    失败 = 0
    完成 = 0

    say(f"  用 {并发进程数} 个进程并发下载"
        f"（诊断实测：1进程 14.0s/只、4进程 4.2s/只、8进程 9.1s/只）")
    say()

    def 写入(code, rows, fields):
        idx = {name: k for k, name in enumerate(fields)}
        buf = []
        for row in rows:
            buf.append((
                code, row[idx["date"]],
                f(row[idx["open"]]), f(row[idx["high"]]),
                f(row[idx["low"]]), f(row[idx["close"]]),
                f(row[idx["volume"]]), f(row[idx["amount"]]),
                f(row[idx["turn"]]), f(row[idx["pctChg"]]),
                i(row[idx["tradestatus"]]), i(row[idx["isST"]]),
            ))
        if buf:
            c.executemany(
                "INSERT OR REPLACE INTO daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", buf)
        return len(buf)

    池 = None
    try:
        池 = mp.Pool(processes=并发进程数, initializer=mp_fetch.初始化子进程)
        for code, rows, fields, err, dt in 池.imap_unordered(
                mp_fetch.取日线, 任务, chunksize=1):
            完成 += 1
            if rows is None:
                mark(c, "daily", code, "fail", err)
                失败 += 1
                状态 = "  失败"
            elif len(rows) == 0:
                # Baostock 在限流/抖动时会返回 error_code=0 但结果集是空的，
                # 不抛异常。如果把它当成功标 ok，这只股票就再也不会被重下 ——
                # 数据永久丢失，而且失败清单里查不到。所以空结果一律算失败。
                mark(c, "daily", code, "empty", "返回0根K线")
                失败 += 1
                状态 = "  空表"
            else:
                n行 = 写入(code, rows, fields)
                if n行 == 0:
                    mark(c, "daily", code, "empty", "写入0行")
                    失败 += 1
                    状态 = "  空表"
                else:
                    mark(c, "daily", code, "ok", f"{n行}根")
                    状态 = f"{n行:>5}根"

            用 = time.time() - t0
            剩 = 用 / 完成 * (len(待办) - 完成)
            say(f"  [{完成:>4}/{len(待办)}] {code} {(名表.get(code) or '')[:6]:<7}"
                f"{状态}  {dt:>5.1f}s   已用 {用时(用)}  剩约 {用时(剩)}")

            if 完成 % 20 == 0:
                c.commit()

            if 完成 == 20:      # 跑满20只再给预估，比3只准
                每只 = (time.time() - t0) / 20
                say()
                say(f"  实测 {每只:.2f} 秒/只（{并发进程数}进程）→ 本次 "
                    f"{len(待办)} 只预计 {用时(每只*len(待办))}")
                if len(待办) < 5000:
                    say(f"  （全量 5556 只按此速度约 {用时(每只*5556)}）")
                say()
    except KeyboardInterrupt:
        say("\n  收到中断，正在保存已完成的进度 ...")
        raise
    finally:
        if 池 is not None:
            池.terminate()
            池.join()
        c.commit()

    总行 = c.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    say(f"\n  ✓ 日线完成，库中共 {总行:,} 行；失败 {失败} 只\n")


# ============================================================
# 任务 3：财务（业绩报表横截面，带公告日）
# ============================================================
def 报告期列表():
    out = []
    # 回溯 3 年而不是 1 年：roe_ttm 要「本期累计 + 上年年报 - 上年同期」，
    # ROE稳定性又要过去 8 期 roe_ttm 的标准差。只多取一年的话，2011 年首次
    # 调仓时手上只有 3 个 roe_ttm 点，拿 3 个点算标准差等于噪声，
    # 而质量因子占 0.25 的权重。多拉 8 个报告期，约 13 分钟，很划算。
    y0 = int(起始日期[:4]) - 3
    for y in range(y0, int(结束日期[:4]) + 1):
        for md in ("0331", "0630", "0930", "1231"):
            d = f"{y}{md}"
            if d <= 结束日期.replace("-", ""):
                out.append(d)
    return out


def 任务_财务(c, 模式="全量"):
    bar()
    say("任务 3 / 7  财务数据（按报告期横截面拉取）")
    say("            体检显示逐股拉要 57.6 小时，横截面只要约 2 小时")
    bar()

    try:
        import akshare as ak
    except Exception as e:
        say(f"  ✗ AKShare 不可用，跳过：{e}\n")
        return

    全部期 = 报告期列表()
    if 模式 == "试运行":
        全部期 = 全部期[-4:]          # 试运行只拉最近 4 期，验证流程即可
        say(f"  试运行：只拉最近 4 个报告期（全量时是 {len(报告期列表())} 个）")

    期 = [p for p in 全部期 if not done(c, "fin", p)]
    say(f"  待拉取 {len(期)} 个报告期（本次计划 {len(全部期)} 个）")
    if not 期:
        say("  全部已完成，跳过\n")
        return
    say()

    列映射 = {
        "eps": ["每股收益"],
        "revenue": ["营业总收入-营业总收入", "营业收入"],
        "rev_yoy": ["营业总收入-同比增长"],
        "np": ["净利润-净利润", "净利润"],
        "np_yoy": ["净利润-同比增长"],
        "bps": ["每股净资产"],
        "roe": ["净资产收益率"],
        "ocfps": ["每股经营现金流量"],
        "gpm": ["销售毛利率"],
    }

    t0 = time.time()
    失败 = 0
    for n, p in enumerate(期, 1):
        r, err = 重试(lambda p=p: ak.stock_yjbb_em(date=p), 次数=4, 首次等待=3.0)
        if r is None or len(r) == 0:
            mark(c, "fin", p, "fail", err or "空表")
            失败 += 1
            say(f"  [{n}/{len(期)}] {p}  ✗ {(err or '空表')[:60]}")
            continue

        df = r
        def col(names):
            for nm in names:
                if nm in df.columns:
                    return df[nm]
            return None

        代码 = col(["股票代码"])
        公告 = col(["最新公告日期"])
        if 代码 is None:
            mark(c, "fin", p, "fail", "无股票代码列")
            失败 += 1
            continue

        import pandas as pd
        out, seen = [], set()
        滤掉 = 0
        vals = {k: col(v) for k, v in 列映射.items()}
        for j in range(len(df)):
            code = str(代码.iloc[j]).zfill(6)
            if code in seen:            # 分页可能重复，去重
                continue
            seen.add(code)
            # 诊断发现：年报期/半年报期接口会把北交所+新三板+B股一起返回
            # （11,506 个代码里沪深A股只有 5,226 个）。这里按前缀白名单过滤。
            if not code.startswith(A股前缀):
                滤掉 += 1
                continue
            ann = 公告.iloc[j] if 公告 is not None else None
            try:
                ann = pd.to_datetime(ann).strftime("%Y-%m-%d") if ann is not None and pd.notna(ann) else None
            except Exception:
                ann = None
            def g(k):
                s = vals[k]
                if s is None:
                    return None
                try:
                    v = float(s.iloc[j])
                    return None if pd.isna(v) else v
                except Exception:
                    return None
            out.append((code, p, ann, g("eps"), g("revenue"), g("rev_yoy"),
                        g("np"), g("np_yoy"), g("bps"), g("roe"),
                        g("ocfps"), g("gpm")))

        c.executemany(
            "INSERT OR REPLACE INTO finance VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", out)
        有公告日 = sum(1 for x in out if x[2])
        mark(c, "fin", p, "ok", f"{len(out)}条/{有公告日}有公告日/滤掉{滤掉}")
        c.commit()

        用 = time.time() - t0
        剩 = 用 / n * (len(期) - n)
        say(f"  [{n}/{len(期)}] {p}  ✓ 沪深A股 {len(out)} 只"
            f"（{有公告日} 带公告日，已滤掉非A股 {滤掉} 只）  还要约 {用时(剩)}")

    总 = c.execute("SELECT COUNT(*) FROM finance").fetchone()[0]
    带日 = c.execute("SELECT COUNT(*) FROM finance WHERE ann_date IS NOT NULL").fetchone()[0]
    say(f"\n  ✓ 财务完成，共 {总:,} 条，其中 {带日:,} 条带公告日"
        f"（{带日/max(总,1)*100:.1f}%）；失败 {失败} 期\n")


# ============================================================
# 任务 4：分红（只取年报期，A股分红以年度为主）
# ============================================================
def 任务_分红(c, 模式="全量"):
    bar()
    say("任务 4 / 7  分红数据（红利因子的原料）")
    bar()

    try:
        import akshare as ak
        import pandas as pd
    except Exception as e:
        say(f"  ✗ AKShare 不可用，跳过：{e}\n")
        return

    # 四个报告期全拉 —— 只拉 1231 会漏掉中期分红。
    # 2024 年新"国九条"之后中期分红大幅增加（700+ 家），只算年报会系统性
    # 低估这些公司的股息率，而股息率是红利因子里权重最高的一项。
    # 回溯 4 年：engine 的「连续分红年数」要回看 5 年（回溯年=5），
    # 只从 2009 起的话，2011 年调仓时这个数最大只能是 2，红利因子 0.3 的权重失真。
    年份 = range(int(起始日期[:4]) - 4, int(结束日期[:4]) + 1)
    报告期 = [f"{y}{q}" for y in 年份 for q in ("0331", "0630", "0930", "1231")]
    报告期 = [x for x in 报告期 if x <= 结束日期.replace("-", "")]
    if 模式 == "试运行":
        全 = len(报告期); 报告期 = 报告期[-2:]
        say(f"  试运行：只拉最近 2 个报告期（全量时是 {全} 个）")
    年报数 = sum(1 for x in 报告期 if x.endswith("1231"))
    报告期 = [x for x in 报告期 if not done(c, "div", x)]
    say(f"  待拉取 {len(报告期)} 个报告期"
        f"（年报 {年报数} 个 + 一季/中期/三季，中期分红必须算进来）")
    if not 报告期:
        say("  全部已完成，跳过\n")
        return
    say("  季度期大多是空的（很多年份本来就没公司做中期分红），空表属于正常结果")
    say()

    失败, 空期 = 0, 0
    for n, p in enumerate(报告期, 1):
        # 年报期是必需品，多重试几次；季度期是增量，空了就空了，别浪费退避时间
        是年报 = p.endswith("1231")
        r, err = 重试(lambda p=p: ak.stock_fhps_em(date=p),
                      次数=(5 if 是年报 else 2),
                      首次等待=(3.0 if 是年报 else 2.0))
        if r is None:
            # AKShare 在「该报告期东财根本没有数据」时不是返回空表，而是内部
            # 拿 None 去下标，抛 TypeError。这不是网络错误，是「没这期数据」。
            # 对季度期来说这完全正常（2006-2015 年几乎没有公司做季度分红），
            # 标成 fail 会让它每次重跑都白试一遍，还在汇总里冒充成真失败。
            无数据 = "NoneType" in str(err) and "subscriptable" in str(err)
            if 无数据 and not 是年报:
                mark(c, "div", p, "ok", "接口无该期数据（季度期，正常）")
                空期 += 1
                say(f"  [{n}/{len(报告期)}] {p}  · 接口无该期数据（季度期，正常）")
                continue
            # 年报期即使报这个错也当失败 —— 年报期不可能没有数据
            mark(c, "div", p, "fail", err or "调用失败")
            失败 += 1
            say(f"  [{n}/{len(报告期)}] {p}  ✗ {(err or '调用失败')[:60]}")
            continue
        if len(r) == 0:
            if 是年报:
                # 2009-2025 任何一个年报期，A股都不可能没有一家公司分红。
                # 空表只可能是被限流了。标 ok 会让整整一年的分红静默消失，
                # 而股息率在红利因子里占 0.7 的权重。
                mark(c, "div", p, "fail", "年报期返回空表，不可信")
                失败 += 1
                say(f"  [{n}/{len(报告期)}] {p} 年报  ✗ 返回空表（不可信，下次会重试）")
            else:
                # 季度期本来就可能一家都没有，空表是正常结果
                mark(c, "div", p, "ok", "本期无分红预案")
                空期 += 1
                say(f"  [{n}/{len(报告期)}] {p}  · 本期无分红预案（正常）")
            continue

        df = r
        def col(*names):
            for nm in names:
                for cc in df.columns:
                    if nm in str(cc):
                        return df[cc]
            return None

        # 列名以诊断实测为准：代码 / 现金分红-现金分红比例 / 总股本 / 预案公告日 ...
        代码 = col("代码")
        现金 = col("现金分红-现金分红比例", "现金分红比例", "派息")
        股本 = col("总股本")
        预案 = col("预案公告日")
        最新 = col("最新公告日期")
        除权 = col("除权除息日")
        登记 = col("股权登记日")
        进度 = col("方案进度")

        if 代码 is None:
            实际列 = [str(x) for x in df.columns]
            mark(c, "div", p, "fail", f"无代码列，实际列名: {实际列}")
            失败 += 1
            say(f"  [{n}/{len(报告期)}] {p}  ✗ 找不到代码列")
            say(f"        实际列名: {实际列}")     # ← 上次漏了这句，导致静默跳过
            continue

        out, seen = [], set()
        滤掉 = 0
        for j in range(len(df)):
            code = str(代码.iloc[j]).zfill(6)
            if code in seen:
                continue
            seen.add(code)
            if not code.startswith(A股前缀):
                滤掉 += 1
                continue

            def d(s):
                if s is None:
                    return None
                try:
                    v = s.iloc[j]
                    return pd.to_datetime(v).strftime("%Y-%m-%d") if pd.notna(v) else None
                except Exception:
                    return None

            def g(s):
                if s is None:
                    return None
                try:
                    v = float(s.iloc[j])
                    return None if pd.isna(v) else v
                except Exception:
                    return None

            def t(s):
                if s is None:
                    return None
                try:
                    v = s.iloc[j]
                    return None if pd.isna(v) else str(v)
                except Exception:
                    return None

            out.append((code, p, d(预案), d(最新), g(现金), g(股本),
                        d(登记), d(除权), t(进度)))

        c.executemany(
            "INSERT OR REPLACE INTO dividend VALUES(?,?,?,?,?,?,?,?,?)", out)
        有派息 = sum(1 for x in out if x[4])
        有预案日 = sum(1 for x in out if x[2])
        mark(c, "div", p, "ok", f"{len(out)}条/{有派息}有派息/{有预案日}有预案日")
        c.commit()
        标 = "年报" if p.endswith("1231") else "中期/季度"
        say(f"  [{n}/{len(报告期)}] {p} {标}  ✓ 沪深A股 {len(out)} 条"
            f"（{有派息} 有现金派息，{有预案日} 有预案公告日，滤掉非A股 {滤掉}）")

    总 = c.execute("SELECT COUNT(*) FROM dividend").fetchone()[0]
    say(f"\n  ✓ 分红完成，共 {总:,} 条；空期 {空期} 个（正常），失败 {失败} 期")
    if 失败:
        say(f"    （失败的报告期会在报告里列出，可以单独重跑补齐）")
    say()

    分红结构体检(c)


def 分红结构体检(c):
    """回答一个必须用数据回答的问题：年报分红和中期分红能不能直接相加？

    如果东财的「年报分红预案」里已经含了当年已派的中期分红，那两者相加就是
    重复计算，股息率会被拔高一倍 —— 这种错误在回测里看起来像超额收益，
    是最危险的一类 bug。反过来如果它们是各自独立的分配方案，就必须相加，
    否则漏掉中期分红。
    这里不猜，直接把数据摆出来。
    """
    bar()
    say("  分红结构体检（决定回测里股息率怎么算）")
    bar()
    try:
        按期 = c.execute(
            "SELECT SUBSTR(report_date,5,4) AS q, COUNT(*), "
            "       COUNT(DISTINCT code) "
            "FROM dividend WHERE cash_per10 > 0 GROUP BY q ORDER BY q").fetchall()
        名 = {"0331": "一季报", "0630": "中报", "0930": "三季报", "1231": "年报"}
        say(f"    {'报告期':<8}{'有派息记录':>12}{'涉及公司':>12}")
        for q, n, k in 按期:
            say(f"    {名.get(q, q):<8}{n:>12,}{k:>12,}")
        say()

        重叠 = c.execute(
            "SELECT SUBSTR(a.report_date,1,4) AS y, COUNT(*), "
            "       AVG(b.cash_per10 * 1.0 / a.cash_per10) "
            "FROM dividend a JOIN dividend b "
            "  ON a.code = b.code "
            " AND SUBSTR(a.report_date,1,4) = SUBSTR(b.report_date,1,4) "
            "WHERE SUBSTR(a.report_date,5,4) = '1231' "
            "  AND SUBSTR(b.report_date,5,4) <> '1231' "
            "  AND a.cash_per10 > 0 AND b.cash_per10 > 0 "
            "GROUP BY y HAVING COUNT(*) >= 10 ORDER BY y").fetchall()
        if not 重叠:
            say("    同一年既有年报分红又有中期分红的公司很少，暂时看不出结构。")
        else:
            say("    同一年「既发年报分红、又发中期分红」的公司：")
            say(f"    {'年份':<8}{'公司数':>10}{'中期÷年报 的平均倍数':>24}")
            for y, n, 比 in 重叠:
                say(f"    {y:<8}{n:>10,}{比:>24.2f}")
            平均比 = sum(x[2] for x in 重叠) / len(重叠)
            say()
            if 平均比 > 0.85:
                say(f"    ⚠ 平均倍数 {平均比:.2f} 接近或超过 1 —— 有重复计算的嫌疑，")
                say("      年报那条可能已经把中期算进去了。回测里不能直接相加。")
            else:
                say(f"    ✓ 平均倍数 {平均比:.2f}，明显小于 1 —— 中期是独立的一笔分配，")
                say("      和年报是两笔钱。回测里股息率应当按滚动 12 个月求和。")
        say()
    except Exception as e:
        say(f"    体检跳过（不影响建库）：{e}")
        say()


# ============================================================
# 任务 5：行业
# ============================================================
def 任务_行业(c, 模式="全量"):
    bar()
    say("任务 5 / 7  行业分类（按年取历史快照）")
    say("            诊断已确认 Baostock 支持历史日期：")
    say("            2015-06-30 → updateDate 2015-06-29（2,853条）")
    say("            所以行业中性化可以正常做，不必关闭")
    bar()

    bs = _bs
    快照日 = [f"{y}-06-30" for y in
              range(int(起始日期[:4]), int(结束日期[:4]) + 1)]
    快照日 = [d for d in 快照日 if d <= 结束日期] + ["当前"]
    if 模式 == "试运行":
        快照日 = 快照日[-3:]
        say(f"  试运行：只取最近 3 个快照（全量时是 {int(结束日期[:4])-int(起始日期[:4])+2} 个）")

    待办 = [d for d in 快照日 if not done(c, "ind", d)]
    say(f"  待取 {len(待办)} 个快照（每个约 60-130 秒）")
    if not 待办:
        n = c.execute("SELECT COUNT(*) FROM industry").fetchone()[0]
        say(f"  全部已完成，跳过。库中共 {n} 条\n")
        return
    say()

    for k, d in enumerate(待办, 1):
        def _q(d=d):
            return bs_rows(bs.query_stock_industry()
                           if d == "当前" else bs.query_stock_industry(date=d))
        r, err = 重试(_q, 次数=3, 首次等待=5.0)
        if r is None or not r[0]:
            say(f"  [{k}/{len(待办)}] {d}  ✗ {(err or '空')[:60]}")
            mark(c, "ind", d, "fail", err or "空")
            c.commit()
            continue
        rows, fields = r
        idx = {n: j for j, n in enumerate(fields)}
        快照 = d if d != "当前" else 结束日期
        out = [(row[idx["code"]], 快照, row[idx["code_name"]],
                row[idx["industry"]], row[idx["industryClassification"]],
                row[idx["updateDate"]]) for row in rows]
        c.executemany("INSERT OR REPLACE INTO industry VALUES(?,?,?,?,?,?)", out)
        有行业 = sum(1 for x in out if x[3])
        实际更新日 = out[0][5] if out else "?"
        mark(c, "ind", d, "ok", f"{len(out)}条@{实际更新日}")
        c.commit()
        say(f"  [{k}/{len(待办)}] {d}  ✓ {len(out):,} 条，"
            f"有行业标签 {有行业:,}，实际 updateDate={实际更新日}")

    总 = c.execute("SELECT COUNT(*) FROM industry").fetchone()[0]
    快照数 = c.execute("SELECT COUNT(DISTINCT snapshot_date) FROM industry").fetchone()[0]
    口径 = (c.execute("SELECT classification FROM industry LIMIT 1").fetchone()
            or ["?"])[0]
    say(f"\n  ✓ 行业完成，{快照数} 个历史快照共 {总:,} 条；分类口径：{口径}")
    say(f"    回测时按调仓日取最近一个不晚于该日的快照 → 无前视偏差\n")


# ============================================================
# 任务 6：指数
# ============================================================
def 任务_指数(c):
    bar()
    say("任务 6 / 7  指数行情（回测基准）")
    bar()
    bs = _bs
    字段 = "date,code,close,pctChg"
    for code, name in 指数列表.items():
        if done(c, "idx", code):
            say(f"  {name} 已完成，跳过")
            continue
        def _q(code=code):
            return bs_rows(bs.query_history_k_data_plus(
                code, 字段, start_date=起始日期, end_date=结束日期,
                frequency="d", adjustflag="3"))
        r, err = 重试(_q, 次数=3)
        if r is None or not r[0]:
            say(f"  ○ {name} ({code}) 取不到：{(err or '空')[:50]}")
            mark(c, "idx", code, "fail", err or "空")
            continue
        rows, fields = r
        idx = {n: k for k, n in enumerate(fields)}
        buf = [(code, row[idx["date"]], f(row[idx["close"]]), f(row[idx["pctChg"]]))
               for row in rows]
        c.executemany("INSERT OR REPLACE INTO index_daily VALUES(?,?,?,?)", buf)
        mark(c, "idx", code, "ok", f"{len(buf)}根")
        c.commit()
        say(f"  ✓ {name} ({code})  {len(buf)} 根K线")
    say()
    say("  说明：这些是价格指数，不含股息再投资。")
    say("  验收标准要求对比『沪深300全收益』，两者每年约差 2-3 个百分点（股息）。")
    say("  回测报告里会同时给出对价格指数和对估算全收益的两套结果。\n")


# ============================================================
# 任务 7：无风险利率
# ============================================================
def 任务_国债(c):
    bar()
    say("任务 7 / 7  10年期国债收益率（股息率门槛的锚）")
    bar()
    if done(c, "bond", "all"):
        n = c.execute("SELECT COUNT(*) FROM bond_yield").fetchone()[0]
        say(f"  已完成，跳过。共 {n} 条\n")
        return
    try:
        import akshare as ak
        import pandas as pd
    except Exception as e:
        say(f"  ✗ 跳过：{e}\n")
        return

    r, err = 重试(lambda: ak.bond_zh_us_rate(start_date="20091231"), 次数=4)
    if r is None or len(r) == 0:
        say(f"  ✗ 失败：{err}\n")
        mark(c, "bond", "all", "fail", err)
        c.commit()
        return
    df = r
    dcol = next((x for x in df.columns if "日期" in str(x)), None)
    ycol = next((x for x in df.columns if "中国" in str(x) and "10年" in str(x)
                 and "2年" not in str(x)), None)
    if dcol is None or ycol is None:
        say(f"  ✗ 找不到需要的列：{list(df.columns)[:10]}\n")
        mark(c, "bond", "all", "fail", f"列名对不上: {list(df.columns)[:10]}")
        c.commit()
        return
    out = []
    for j in range(len(df)):
        try:
            d = pd.to_datetime(df[dcol].iloc[j]).strftime("%Y-%m-%d")
            v = float(df[ycol].iloc[j])
            if pd.notna(v):
                out.append((d, v))
        except Exception:
            continue
    c.executemany("INSERT OR REPLACE INTO bond_yield VALUES(?,?)", out)
    mark(c, "bond", "all")
    c.commit()
    if out:
        say(f"  ✓ {len(out)} 条，{out[0][0]} 至 {out[-1][0]}")
        say(f"    最新 10 年期国债收益率：{out[-1][1]:.2f}%\n")


# ============================================================
# 汇总
# ============================================================
def 汇总(c, 模式):
    bar("=")
    say("建库完成 · 汇总")
    bar("=")

    def cnt(t):
        try:
            return c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            return 0

    统计 = {
        "股票名录": cnt("stock_basic"),
        "日线行数": cnt("daily"),
        "财务条数": cnt("finance"),
        "分红条数": cnt("dividend"),
        "行业条数": cnt("industry"),
        "指数行数": cnt("index_daily"),
        "国债条数": cnt("bond_yield"),
    }
    for k, v in 统计.items():
        say(f"  {k:<10} {v:>12,}")

    say()
    rng = c.execute("SELECT MIN(date), MAX(date) FROM daily").fetchone()
    if rng and rng[0]:
        say(f"  行情区间  {rng[0]}  至  {rng[1]}")
    n股 = c.execute("SELECT COUNT(DISTINCT code) FROM daily").fetchone()[0]
    say(f"  有行情的股票数  {n股:,}")
    退 = c.execute("SELECT COUNT(*) FROM stock_basic WHERE type='1' "
                   "AND out_date IS NOT NULL AND TRIM(out_date)!=''").fetchone()[0]
    say(f"  其中已退市      {退:,}  ← 回测会包含它们")

    大小 = os.path.getsize(DB) / 1024 / 1024 if os.path.exists(DB) else 0
    say(f"  数据库大小      {大小:.0f} MB")
    say()

    # 失败项
    问题 = []
    for task, 名 in [("daily", "日线"), ("fin", "财务"), ("div", "分红"),
                     ("ind", "行业"), ("idx", "指数"), ("bond", "国债")]:
        bad = 失败清单(c, task)
        if bad:
            问题.append((名, bad))
    if 问题:
        say("  下列项目有失败，重新双击本脚本会自动只补这些：")
        for 名, bad in 问题:
            say(f"    {名}: {len(bad)} 项  例如 {bad[:5]}")
    else:
        say("  ✓ 没有失败项")
    say()

    # 真实股价分布 + 资金测算（体检时因快照失败没算成，这里用真实收盘价补上）
    测算 = {}
    try:
        last = c.execute("SELECT MAX(date) FROM daily").fetchone()[0]
        # 重要：库里 close 是后复权价，不能当真实价用。
        # 真实均价 = amount / volume（两者都不受复权影响）
        # 流通市值 = 均价 × (volume×100/turn) = amount × 100 / turn
        rows = c.execute("""
            SELECT d.code, b.name,
                   d.amount / d.volume        AS vwap,
                   d.amount * 100.0 / d.turn  AS mktcap
            FROM daily d JOIN stock_basic b ON b.code=d.code
            WHERE d.date=? AND d.volume>0 AND d.turn>0 AND d.amount>0
              AND (d.is_st IS NULL OR d.is_st=0)
              AND (b.out_date IS NULL OR TRIM(b.out_date)='')
        """, (last,)).fetchall()
        prices = sorted(r[2] for r in rows)
        caps = sorted(r[3] for r in rows)
        if prices:
            import statistics as st
            def q(p):
                return prices[min(int(len(prices) * p), len(prices) - 1)]
            测算 = {
                "日期": last, "有效股票数": len(prices),
                "股价分位": {"5%": round(q(.05), 2), "25%": round(q(.25), 2),
                             "50%": round(q(.5), 2), "75%": round(q(.75), 2),
                             "95%": round(q(.95), 2)},
                "一手中位金额": round(q(.5) * 100, 0),
            }
            def qc(p):
                return caps[min(int(len(caps) * p), len(caps) - 1)]
            测算["流通市值分位_亿元"] = {
                "10%": round(qc(.10) / 1e8, 1), "30%": round(qc(.30) / 1e8, 1),
                "50%": round(qc(.50) / 1e8, 1), "90%": round(qc(.90) / 1e8, 1)}
            测算["市值最小30%分界_亿元"] = round(qc(.30) / 1e8, 1)

            bar()
            say(f"真实股价与市值分布（{last}，剔除 ST 与已退市，共 {len(prices)} 只）")
            say("  价格口径 = 成交额/成交量（真实均价），不是库里的后复权收盘价")
            bar()
            say("  股价分位: " + "  ".join(
                f"{k}={v}" for k, v in 测算["股价分位"].items()))
            say(f"  一手金额中位数: {测算['一手中位金额']:.0f} 元")
            say()
            say("  流通市值分位(亿元): " + "  ".join(
                f"{k}={v}" for k, v in 测算["流通市值分位_亿元"].items()))
            say(f"  → 策略要剔除的『最小30%市值』分界线约 "
                f"{测算['市值最小30%分界_亿元']} 亿元")
            say()
            say("  以 2500 元，目标持 N 只时买得起多少：")
            say()
            say("    N    每只预算    买得起    占比")
            tbl = []
            for N in [2, 3, 4, 5, 6, 8]:
                预算 = 2500 / N
                可买 = sum(1 for p in prices if p * 100 <= 预算)
                tbl.append({"N": N, "每只预算": round(预算),
                            "可买": 可买, "占比%": round(可买 / len(prices) * 100, 1)})
                say(f"   {N:>2}    {预算:>7.0f}    {可买:>6}    "
                    f"{可买/len(prices)*100:>5.1f}%")
            测算["资金可行性"] = tbl
            say()
            say("  这张表只说明『买得起多少』，")
            say("  『买得起的里面有多少是达标优质股』要等第三步筛出来才知道。")
            say()
    except Exception as e:
        say(f"  股价测算跳过：{e}\n")

    报告 = {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "模式": 模式, "耗时秒": round(time.time() - _t_start, 1),
        "统计": 统计,
        "行情区间": list(rng) if rng else None,
        "有行情股票数": n股, "已退市股票数": 退,
        "数据库MB": round(大小, 1),
        "失败项": {名: bad[:200] for 名, bad in 问题},
        "股价测算": 测算,
    }
    p = os.path.join(OUT_DIR, "建库结果.json")
    with open(p, "w", encoding="utf-8") as fp:
        json.dump(报告, fp, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUT_DIR, "建库日志.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(日志))

    bar("=")
    say(f"总耗时 {用时(time.time() - _t_start)}")
    say(f"数据库：{DB}")
    say(f"报告：  {p}")
    say()
    if 模式 == "试运行":
        say("  ▶ 这是试运行（只下了少量股票）。")
        say("    把 output\\建库结果.json 发回给 Claude 确认无误后，")
        say("    再选『2』跑全量。")
    else:
        say("  ▶ 全量建库完成。把 output\\建库结果.json 发回给 Claude，")
        say("    就能进行第三步：因子计算与回测。")
    say()


# ============================================================
def main():
    say()
    bar("=")
    say("   A股选股工具 · 第二步：建立本地数据库")
    bar("=")
    say()

    模式 = "试运行"
    if len(sys.argv) > 1 and sys.argv[1] == "full":
        模式 = "全量"
    say(f"  模式：{模式}")
    if 模式 == "试运行":
        say(f"  只下载 {试运行股票数} 只股票（均匀抽样），约 10-20 分钟")
        say("  目的是先跑通全流程，确认没问题再跑全量")
    else:
        say("  下载全市场，可能需要 3-8 小时")
        say("  可以随时关掉窗口，下次双击会从断点接着跑")
    say()

    free = shutil.disk_usage(ROOT).free / 1024**3
    say(f"  可用磁盘空间：{free:.1f} GB")
    if free < 3:
        say("  ⚠ 空间不足 3GB，建议清理后再跑全量")
    say()

    c = open_db()
    bs_login()
    say("  Baostock 登录成功\n")

    try:
        任务_股票名录(c)
        codes = 取股票列表(c, 限制=(试运行股票数 if 模式 == "试运行" else None))
        任务_日线(c, codes)
        任务_财务(c, 模式)
        任务_分红(c, 模式)
        任务_行业(c, 模式)
        任务_指数(c)
        任务_国债(c)
        汇总(c, 模式)
    except KeyboardInterrupt:
        c.commit()
        say("\n\n  已中断。进度都存好了，下次双击会从断点继续。\n")
    finally:
        try:
            c.commit(); c.close()
        except Exception:
            pass
        try:
            _bs.logout()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say("\n出现意外错误，请把下面内容发回给 Claude：\n")
        traceback.print_exc()
        try:
            with open(os.path.join(OUT_DIR, "建库日志.txt"), "w", encoding="utf-8") as fp:
                fp.write("\n".join(日志) + "\n\n" + traceback.format_exc())
        except Exception:
            pass
    input("\n按回车键关闭...")
