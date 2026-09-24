# -*- coding: utf-8 -*-
"""
A股选股工具 — 回测引擎（数据层 + 因子层 + 组合层 + 执行层）
================================================================
设计原则，每一条都对应一个已确认的事实：

PIT（无前视偏差）
  · 财务只用 ann_date <= 调仓日 的最新报告期
  · 分红只用 plan_ann_date <= 调仓日
  · 行业取 snapshot_date <= 调仓日 的最近一个快照
  · 价量只用 调仓日之前 的数据，成交发生在调仓日开盘

价格口径
  · 库里 close/open 是后复权价 —— 只能用来算收益率，不能当真实价格
  · 真实价格 = amount / volume（当日成交均价）
  · 流通市值 = amount × 100 / turn   （turn 是换手率%）

不做参数寻优
  · 四组因子等权合成，权重不可调
  · 绝对门槛锚在「市场自身分布」与「无风险利率」上，不从回测里挑

作者: Claude
"""

import os, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "ashare.db")

# ============================================================
# 交易成本（2023-08 印花税减半后的现行费率）
# ============================================================
# 佣金：费率可谈，但「单笔最低 5 元」来自证监发〔2002〕21号，至今未废止。
# 对小资金账户，真正起作用的永远是那个 5 元下限：
#   5 ÷ 0.00015 = 33,333 元，单笔不到这个数，费率是多少都不影响实收佣金。
# 2026-09-08 中证协已就「5元最低」存废启动行业调研（维持 / 降至3元 / 取消
# 三个备选），但截至目前无结论，所以这里仍按 5 元建模。
佣金费率 = 0.00015        # 万 2.5
佣金最低 = 5.0            # 单笔单向不足 5 元按 5 元收
印花税率 = 0.0005         # 0.05%，仅卖出
过户费率 = 0.00001        # 0.001%，双边
滑点率 = 0.0010           # 单边 0.1%（中小盘保守）

# ============================================================
# 股票池与组合约束
# ============================================================
最少上市天数 = 252
市值剔除分位 = 0.30       # 剔除最小 30% 市值（壳价值污染，LSY 2019）
流动性剔除分位 = 0.10     # 剔除日均成交额最低 10%
估值剔除分位 = 0.20       # 剔除 EP 最低（最贵）的 20%
单票上限 = 0.10
单行业上限 = 0.30
持仓上限 = 35
波动率门槛分位 = 0.70     # 波动率低于当期截面 70 分位才算「低波」
换手变化上限 = 1.5        # 单期持仓数变化不超过 ±50%

# 涨跌停判定阈值（略小于名义值，避免浮点误差把刚好涨停的判成没涨停）
# ST 分两档：2026-07-06 起沪深主板风险警示股涨跌幅由 ±5% 放宽到 ±10%
#   依据：上证发〔2026〕41号《上海证券交易所交易规则（2026年修订）》
#         2026-04-24 发布、2026-07-06 施行；深交所同步
#         证监会上海监管局解读："沪深主板将风险警示股票的涨跌幅由5%放宽至10%，
#         创业板、科创板维持20%不变，北交所维持30%不变。"
# 注意：创业板/科创板的 ST 股涨跌幅一直是 ±20%，从来不是 ±5% —— 板块属性
#       决定涨跌幅，ST 标记不单独降档。所以下面先判双创。
ST新规日 = "2026-07-06"
涨停阈值 = {"主板": 0.098, "双创": 0.198,
            "ST": 0.048,        # 2026-07-06 之前的沪深主板 ST
            "ST宽": 0.098,      # 2026-07-06 起的沪深主板 ST
            "北交所": 0.298}


# 沪深交易所定期报告的法定披露截止日
法定截止 = {"0331": ("同年", "-04-30"),     # 一季报：4月30日
            "0630": ("同年", "-08-31"),     # 半年报：8月31日
            "0930": ("同年", "-10-31"),     # 三季报：10月31日
            "1231": ("次年", "-04-30")}     # 年报：次年4月30日


def _财务可用日(财务):
    """算出每一条财报「最早可以拿来用」的日期。

    为什么不能直接用 ann_date：
      库里的 ann_date 取自东财业绩报表的「最新公告日期」，它不是首次披露日，
      而是「最近一次提到这个报告期的公告」的日期。2017 年中报那一条，会被
      2018 年中报（里面含 2017 同期对比数）把日期顶到一年之后。
      本机实测：公告延迟中位数 396 天 —— 明显不是真实披露节奏
      （分红表的预案公告日中位只有 101 天，是正常的）。
      直接用它不会造成未来函数（只会更晚看到数据），但会让质量因子
      长期在用一年半前的财报，等于把因子废掉一半。

    取法：可用日 = min(ann_date, 法定披露截止日)
      · ann_date 是「最近一次公告日」，必然 >= 真实首次披露日 —— 是个上界
      · 法定截止日对守规矩的公司也 >= 真实披露日 —— 也是个上界
      · 两个上界取小，仍然 >= 真实披露日，所以不会提前看到数据，
        同时把被顶到一年后的那些拉回合理位置
      残留风险：极少数延迟披露（超过法定截止日）的公司会被当成按时披露。
      这类几乎都是 ST / 退市风险公司，而股票池本来就剔除 ST。
    """
    r = 财务["report_date"].astype(str)
    年 = pd.to_numeric(r.str[:4], errors="coerce")
    期 = r.str[4:]
    截止 = pd.Series(pd.NaT, index=财务.index, dtype="datetime64[ns]")
    for k, (哪年, 月日) in 法定截止.items():
        m = 期 == k
        if not m.any():
            continue
        y = 年[m] + (1 if 哪年 == "次年" else 0)
        截止.loc[m] = pd.to_datetime(
            y.astype("Int64").astype(str) + 月日, errors="coerce")
    ann = pd.to_datetime(财务["ann_date"], errors="coerce")

    # 硬下界：报告期末。公告日不可能早于报告期结束 —— 那种记录只能是
    # 数据错误，但如果照单全收，就等于提前看到了未来的财报。
    # 这条是 tests/test_pit_and_execution.py 里的属性测试逼出来的：
    # 随机生成公告日偏移量后，20101231 这条被喂了 2009-11-11，
    # 原来的写法直接采信了它。真实数据里这类记录很少但确实存在
    # （美股 Compustat 的 rdq 里同样有 0.007% 早于 datadate）。
    期末 = pd.to_datetime(r, format="%Y%m%d", errors="coerce")
    合法 = ann.notna() & (ann > 期末) & (ann < 截止)
    可用 = ann.where(合法, 截止)
    return 可用.dt.strftime("%Y-%m-%d")


def 应用配置(cfg):
    """把 config.json 的值注入本模块的全局参数。

    所有参数都留了模块级默认值，所以即使配置缺项、或者压根不调这个函数，
    引擎仍然能按本项目验证过的那套默认值跑起来。
    """
    global 佣金费率, 佣金最低, 印花税率, 过户费率, 滑点率
    global 最少上市天数, 市值剔除分位, 流动性剔除分位, 估值剔除分位
    global 单票上限, 单行业上限, 持仓上限, 波动率门槛分位, 换手变化上限
    global 单笔最小金额, 因子权重, 剔除ST, 门槛开关

    c = cfg.get("资金与成本", {})
    佣金费率 = float(c.get("佣金费率", 佣金费率))
    佣金最低 = float(c.get("佣金最低", 佣金最低))
    印花税率 = float(c.get("印花税率", 印花税率))
    过户费率 = float(c.get("过户费率", 过户费率))
    滑点率 = float(c.get("滑点率", 滑点率))
    单笔最小金额 = float(c.get("单笔最小金额", 单笔最小金额))

    p = cfg.get("股票池", {})
    最少上市天数 = int(p.get("最少上市天数", 最少上市天数))
    市值剔除分位 = float(p.get("市值剔除分位", 市值剔除分位))
    流动性剔除分位 = float(p.get("流动性剔除分位", 流动性剔除分位))
    估值剔除分位 = float(p.get("估值剔除分位", 估值剔除分位))
    单票上限 = float(p.get("单票上限", 单票上限))
    单行业上限 = float(p.get("单行业上限", 单行业上限))
    剔除ST = bool(p.get("剔除ST", True))

    t = cfg.get("调仓", {})
    持仓上限 = int(t.get("持仓上限", 持仓上限))
    换手变化上限 = float(t.get("换手变化上限", 换手变化上限))

    g = cfg.get("绝对门槛", {})
    波动率门槛分位 = float(g.get("波动率门槛分位", 波动率门槛分位))
    门槛开关 = {
        "ROE": bool(g.get("启用_ROE高于历史中位", True)),
        "股息": bool(g.get("启用_股息率高于国债", True)),
        "股息倍数": float(g.get("股息率门槛倍数", 1.0)),
        "波动": bool(g.get("启用_波动率低于分位", True)),
        "EP": bool(g.get("启用_EP为正", True)),
    }
    因子权重 = dict(cfg.get("因子权重", 因子权重))
    return cfg


剔除ST = True
门槛开关 = {"ROE": True, "股息": True, "股息倍数": 1.0, "波动": True, "EP": True}


def 板块(code, 是ST=False, 日期=None):
    """判涨跌停要用的板块口径。

    上一版这个函数永远只返回「主板」或「双创」，涨停阈值里的 "ST" 那一档
    是死代码 —— 结果 ST 股按 ±9.8% 判涨跌停，而实际限制是 ±5%，
    等于系统性高估了 ST 股买得到、卖得掉的概率。
    注意：创业板/科创板的风险警示股票涨跌幅限制仍然是 ±20%，
    所以「双创」要先判，不能一看到 ST 就套 ±5%。
    """
    c = code.split(".")[-1]
    if c.startswith(("30", "68")):
        return "双创"           # 双创的 ST 股也是 ±20%，必须先判
    if not 是ST:
        return "主板"
    return "ST宽" if (日期 and 日期 >= ST新规日) else "ST"


# ============================================================
# 数据加载
# ============================================================
class 数据:
    """把数据库一次性读进内存，之后全部离线计算。"""

    def __init__(self, db=DB, 起始="2010-01-01", 结束=None, 说=print):
        self.说 = 说
        self.db = db
        if not os.path.exists(db):
            raise FileNotFoundError(f"找不到数据库：{db}\n请先跑完 02_build_database.bat")
        c = sqlite3.connect(db)
        结束 = 结束 or c.execute("SELECT MAX(date) FROM daily").fetchone()[0]
        self.起始, self.结束 = 起始, 结束

        # ---- 分块加载：预分配矩阵，按股票分批填充 ----
        # 早先的写法是一次 read_sql 读成长表再 pivot，全量数据下峰值要 2.1 GB。
        # 分块填充省掉那张 1.16 GB 的中间长表；
        # 又把 high/low 在加载时直接压成一个「一字板」布尔矩阵，
        # 并丢掉用不到的 pct_chg。峰值降到 0.7 GB 上下。
        说(f"  读取日线 {起始} ~ {结束} ...")
        日期 = [r[0] for r in c.execute(
            "SELECT DISTINCT date FROM daily WHERE date>=? AND date<=? "
            "ORDER BY date", (起始, 结束))]
        全码 = [r[0] for r in c.execute(
            "SELECT DISTINCT code FROM daily ORDER BY code")]
        # 只保留沪深A股（北交所/新三板/B股在财务表里已滤，这里再保一道）
        代码 = [x for x in 全码
                if x.split(".")[-1].startswith(("60", "68", "00", "30"))]
        nT, nC = len(日期), len(代码)
        说(f"    {nT:,} 个交易日 × {nC:,} 只股票"
          f"（已剔除非沪深A股 {len(全码)-nC} 只）")

        行号 = {d: k for k, d in enumerate(日期)}
        列号 = {x: k for k, x in enumerate(代码)}

        def 空(dtype="float32", 填=np.nan):
            return np.full((nT, nC), 填, dtype=dtype)

        A = {k: 空() for k in ("close", "open", "amount", "volume", "turn")}
        A["ts"] = 空("int8", 0)
        A["st"] = 空("int8", 0)
        A["flat"] = 空("int8", 0)       # 一字板：high==low，完全不可成交

        取列 = ("open", "close", "amount", "volume", "turn",
                "trade_status", "is_st", "high", "low")
        批 = 200          # 批越小，临时开销越低；这一项不随股票总数增长
        for b in range(0, nC, 批):
            片 = 代码[b:b + 批]
            q = ("SELECT code,date," + ",".join(取列) + " FROM daily "
                 "WHERE date>=? AND date<=? AND code IN (%s)"
                 % ",".join("?" * len(片)))
            df = pd.read_sql(q, c, params=[起始, 结束] + 片)
            if not len(df):
                continue
            r = df["date"].map(行号).to_numpy(dtype="float64")
            k = df["code"].map(列号).to_numpy(dtype="float64")
            # 一律走 to_numeric：SQLite 是弱类型，同一列混进字符串或 BLOB
            # 都是可能的，不能假设干净。
            数 = {列: pd.to_numeric(df[列], errors="coerce")
                     .to_numpy(dtype="float64") for 列 in 取列}
            del df            # 字符串列在这里就释放，不带进后面的掩码运算

            ok = np.isfinite(r) & np.isfinite(k)
            ri = r[ok].astype(np.int64)
            ki = k[ok].astype(np.int64)
            for 键, 列 in (("close", "close"), ("open", "open"),
                           ("amount", "amount"), ("volume", "volume"),
                           ("turn", "turn")):
                A[键][ri, ki] = 数[列][ok].astype("float32")
            A["ts"][ri, ki] = np.nan_to_num(
                数["trade_status"][ok], nan=0).clip(0, 1).astype("int8")
            A["st"][ri, ki] = np.nan_to_num(
                数["is_st"][ok], nan=0).clip(0, 1).astype("int8")
            h, l = 数["high"][ok], 数["low"][ok]
            A["flat"][ri, ki] = (np.isfinite(h) & np.isfinite(l)
                                 & (h == l)).astype("int8")
            del 数, r, k, ok, ri, ki, h, l
            if (b // 批) % 8 == 0:
                说(f"    已载入 {min(b+批, nC):,}/{nC:,} 只")

        def DF(a):
            return pd.DataFrame(a, index=日期, columns=代码)

        self.收盘 = DF(A["close"])       # 后复权，只用于算收益率
        self.开盘 = DF(A["open"])        # 后复权，用于涨跌停开盘判断
        self.成交额 = DF(A["amount"])
        self.成交量 = DF(A["volume"])
        self.换手 = DF(A["turn"])
        self.可交易 = DF(A["ts"])
        self.ST = DF(A["st"])
        self.一字板 = DF(A["flat"])
        del A

        self.交易日 = 日期
        用量 = sum(x.values.nbytes for x in
                   (self.收盘, self.开盘, self.成交额, self.成交量,
                    self.换手, self.可交易, self.ST, self.一字板))
        说(f"    矩阵占用 {用量/1024**3:.2f} GB")

        # 真实价格与市值（不受复权影响）
        self.真实价 = (self.成交额 / self.成交量.replace(0, np.nan)).astype("float32")
        self.流通市值 = (self.成交额 * 100.0 /
                        self.换手.replace(0, np.nan)).astype("float32")
        # 停牌日没有成交，前向填充最近一个有效值
        self.真实价 = self.真实价.ffill(limit=20)
        self.流通市值 = self.流通市值.ffill(limit=20)

        说("  读取名录 / 财务 / 分红 / 行业 / 指数 / 国债 ...")
        self.名录 = pd.read_sql("SELECT * FROM stock_basic WHERE type='1'", c)
        self.名录 = self.名录.set_index("code")

        self.财务 = pd.read_sql(
            "SELECT code,report_date,ann_date,eps,bps,roe,gpm,np,revenue "
            "FROM finance WHERE ann_date IS NOT NULL", c)
        self.财务["ann_date"] = pd.to_datetime(
            self.财务["ann_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        self.财务 = self.财务.dropna(subset=["ann_date"])
        说(f"    财务 {len(self.财务):,} 条 / {self.财务['code'].nunique():,} 只")

        self.分红 = pd.read_sql(
            "SELECT code,report_date,plan_ann_date,cash_per10,progress "
            "FROM dividend", c)
        if len(self.分红):
            # 被否决或取消的方案不是钱，不能计入股息
            废 = self.分红["progress"].astype(str).str.contains(
                "取消|否决", na=False)
            if 废.any():
                说(f"    剔除已取消/被否决的分红方案 {int(废.sum())} 条")
                self.分红 = self.分红[~废]
        if len(self.分红):
            self.分红["plan_ann_date"] = pd.to_datetime(
                self.分红["plan_ann_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        说(f"    分红 {len(self.分红):,} 条")

        self.财务["可用日"] = _财务可用日(self.财务)

        self.行业 = pd.read_sql("SELECT * FROM industry", c)
        说(f"    行业 {len(self.行业):,} 条 / "
          f"{self.行业['snapshot_date'].nunique() if len(self.行业) else 0} 个快照")

        self.指数 = pd.read_sql("SELECT * FROM index_daily", c)
        self.国债 = pd.read_sql("SELECT * FROM bond_yield", c)
        c.close()

        self._预处理财务()
        self._预处理行业()

    # --------------------------------------------------------
    def _预处理财务(self):
        """把累计口径的 eps 换算成 TTM，并按公告日排好序。"""
        f = self.财务.copy()
        f["year"] = f["report_date"].str[:4].astype(int)
        f["q"] = f["report_date"].str[4:].map(
            {"0331": 1, "0630": 2, "0930": 3, "1231": 4})
        f = f.dropna(subset=["q"])
        f["q"] = f["q"].astype(int)
        f = f.sort_values(["code", "year", "q"])

        # eps_ttm = 本期累计 + 上年年报 - 上年同期累计；年报期直接取本期
        年报 = f[f["q"] == 4].set_index(["code", "year"])["eps"]
        同期 = f.set_index(["code", "year", "q"])["eps"]
        上年报 = f.set_index(["code", "year"]).index.map(
            lambda k: 年报.get((k[0], k[1] - 1), np.nan))
        上同期 = pd.MultiIndex.from_arrays(
            [f["code"], f["year"] - 1, f["q"]])
        f["上年报eps"] = np.asarray(上年报, dtype="float64")
        f["上同期eps"] = 同期.reindex(上同期).values

        f["eps_ttm"] = np.where(
            f["q"] == 4, f["eps"],
            f["eps"] + f["上年报eps"] - f["上同期eps"])
        # 上年数据缺失时退化为当期累计年化
        缺 = f["eps_ttm"].isna()
        f.loc[缺, "eps_ttm"] = f.loc[缺, "eps"] * (4.0 / f.loc[缺, "q"])

        f["roe_ttm"] = np.where(
            (f["bps"].notna()) & (f["bps"] > 0),
            f["eps_ttm"] / f["bps"] * 100.0, np.nan)

        self.财务 = f.sort_values("ann_date").reset_index(drop=True)

    def _预处理行业(self):
        if not len(self.行业):
            self.行业快照 = []
            return
        self.行业 = self.行业[self.行业["industry"].astype(str).str.len() > 0]
        # 用「门类+大类」两位数字级别，太细会让 30% 上限失效
        self.行业["ind"] = self.行业["industry"].astype(str).str[:3]
        self.行业快照 = sorted(self.行业["snapshot_date"].unique())

    # --------------------------------------------------------
    def 取行业(self, 日期):
        """返回 {code: 行业}，用不晚于该日期的最近一个快照。"""
        可用 = [s for s in self.行业快照 if s <= 日期]
        if not 可用:
            可用 = self.行业快照[:1]
        if not 可用:
            return {}
        快照 = 可用[-1]
        子 = self.行业[self.行业["snapshot_date"] == 快照]
        return dict(zip(子["code"], 子["ind"]))

    def 取财务(self, 日期):
        """返回每只股票在该日期可见的最新一期财务（PIT）。用「可用日」而非
        ann_date —— 原因见 _财务可用日 的说明。"""
        可见 = self.财务[self.财务["可用日"] <= 日期]
        if not len(可见):
            return pd.DataFrame()
        最新 = 可见.groupby("code").tail(1).set_index("code")
        return 最新

    def 取分红(self, 日期, 回溯年=5):
        """返回 {code: (每股股息, 连续分红年数)}，只用调仓日之前已公告的预案。

        口径 = 财年归集：取「年报预案已经公告」的最近那个财年，把该财年
        各报告期（一季/中期/三季/年报）的派息全部加总。

        为什么不是上一版的 tail(1)：
          东财按报告期存分红，一家公司发了中期分红之后，report_date 最大的
          那一条就变成中期那条。tail(1) 会拿 0.2 元的中期去顶替 0.5 元的年报，
          股息率当场腰斩 —— 而且恰恰打击那些分红更积极的公司，方向完全反了。

        为什么要加总（可加性是查证过的，不是假设）：
          若年报那条已含当年中期，则中期 ⊂ 年报，必然 中期 ≤ 年报 恒成立。
          本机数据里有大量「中期 > 年报」的公司×年组合，算术上证伪了包含关系。
          外部对账也一致：招商银行 2024 年报 20.00 元，2025 年首次中期分红后
          年报那条掉到 10.03，中期 10.13 —— 两者相加才约等于上一年的 20.00。

        为什么不是滚动 12 个月：
          中期分红普及的那一年，滚动窗口会同时罩住「上一财年的年报分红」和
          「本财年的中期分红」，等于算了一年半的分红，系统性虚高。
          财年归集没有这个问题，而且与中证红利指数的官方口径一致 ——
          中证红利正是本策略的基准之一，口径对齐才比得出真高低。

        金额为空的行（方案进度=预披露之类只有意向没有金额的占位）按 0 计入，
        不会污染求和。
        """
        if not len(self.分红):
            return pd.DataFrame()
        可见 = self.分红[(self.分红["plan_ann_date"].notna()) &
                        (self.分红["plan_ann_date"] <= 日期)].copy()
        if not len(可见):
            return pd.DataFrame()
        可见["财年"] = 可见["report_date"].astype(str).str[:4]
        可见["派息"] = pd.to_numeric(可见["cash_per10"], errors="coerce").fillna(0.0)

        # 基准财年 = 该股票「年报预案已公告」的最近一个财年
        年报 = 可见[可见["report_date"].astype(str).str[4:] == "1231"]
        if not len(年报):
            return pd.DataFrame()
        基准年 = 年报.groupby("code")["财年"].max().rename("基准年")

        本年 = 可见.join(基准年, on="code")
        本年 = 本年[本年["财年"] == 本年["基准年"]]
        每股股息 = (本年.groupby("code")["派息"].sum() / 10.0).rename("每股股息")

        # 连续分红年数：近 回溯年 个财年里，全年派息 > 0 的财年数
        近 = 可见[可见["财年"] >= str(int(日期[:4]) - 回溯年)]
        年度 = 近.groupby(["code", "财年"])["派息"].sum().reset_index()
        计数 = (年度[年度["派息"] > 0].groupby("code")["财年"]
                .nunique().rename("分红年数"))
        # 还没公告过任何年报预案的公司（次新股等）会只出现在「分红年数」里，
        # 每股股息 是 NaN。补成 0 —— 语义是「没有已公告的分红」，不是「未知」。
        # 留 NaN 会让下游的百分位排名和股息率门槛按缺失处理，行为不可控。
        return pd.concat([每股股息, 计数], axis=1).fillna(
            {"分红年数": 0, "每股股息": 0.0})

    def 取无风险利率(self, 日期):
        b = self.国债[self.国债["date"] <= 日期]
        if not len(b):
            return 2.5
        return float(b.iloc[-1]["cn10y"])


# ============================================================
# 因子计算（全部在调仓日、只用调仓日之前的数据）
# ============================================================
def 截面因子(D, 调仓日, 窗口=250):
    """
    返回一张 DataFrame，index=code，包含：
      流通市值 / 真实价 / 波动率 / 最大回撤 / 日均成交额 / 上市天数
      roe_ttm / gpm / roe稳定性 / 每股股息 / 分红年数 / 股息率 / EP / 行业
    全部只用 调仓日之前 的信息。
    """
    d = D.交易日
    if 调仓日 not in d:
        return pd.DataFrame()
    i = d.index(调仓日)
    if i < 30:
        return pd.DataFrame()
    窗 = slice(max(0, i - 窗口), i)          # 不含调仓日本身
    前一日 = d[i - 1]

    收 = D.收盘.iloc[窗]
    日收益 = 收.pct_change()

    out = pd.DataFrame(index=D.收盘.columns)
    out["真实价"] = D.真实价.iloc[i - 1]
    out["流通市值"] = D.流通市值.iloc[i - 1]
    out["波动率"] = 日收益.std() * np.sqrt(252)
    out["最大回撤"] = (收 / 收.cummax() - 1).min()
    out["日均成交额"] = D.成交额.iloc[窗].mean()
    out["有效天数"] = 收.notna().sum()

    # 当日状态（用于可交易性判断）
    out["ST"] = D.ST.iloc[i]
    out["可交易"] = D.可交易.iloc[i]

    # 上市天数
    ipo = pd.to_datetime(D.名录["ipo_date"], errors="coerce")
    out["上市天数"] = (pd.Timestamp(调仓日) - ipo.reindex(out.index)).dt.days

    # 财务（PIT）
    fin = D.取财务(调仓日)
    if len(fin):
        六位 = pd.Series(out.index, index=out.index).str.split(".").str[-1]
        out["roe_ttm"] = 六位.map(fin["roe_ttm"])
        out["gpm"] = 六位.map(fin["gpm"])
        out["eps_ttm"] = 六位.map(fin["eps_ttm"])
        out["bps"] = 六位.map(fin["bps"])
        # ROE 稳定性：过去 8 期 roe_ttm 的标准差
        可见 = D.财务[D.财务["可用日"] <= 调仓日]
        近8 = (可见.groupby("code")["roe_ttm"]
               .apply(lambda s: s.tail(8).std()))
        out["roe波动"] = 六位.map(近8)
    else:
        for c in ("roe_ttm", "gpm", "eps_ttm", "bps", "roe波动"):
            out[c] = np.nan

    # 分红（PIT）
    div = D.取分红(调仓日)
    if len(div):
        六位 = pd.Series(out.index, index=out.index).str.split(".").str[-1]
        out["每股股息"] = 六位.map(div["每股股息"])
        out["分红年数"] = 六位.map(div["分红年数"]).fillna(0)
    else:
        out["每股股息"] = np.nan
        out["分红年数"] = 0.0

    out["股息率"] = out["每股股息"] / out["真实价"]
    out["EP"] = out["eps_ttm"] / out["真实价"]

    # 行业（PIT）
    ind = D.取行业(调仓日)
    out["行业"] = pd.Series(out.index, index=out.index).map(ind)

    return out


# ============================================================
# 股票池
# ============================================================
def 建股票池(F, D, 调仓日):
    """返回 (可选股票 index, 各步骤剔除计数)"""
    步骤 = {}
    m = F["真实价"].notna() & (F["真实价"] > 0)
    步骤["有价格"] = int(m.sum())

    m &= F["有效天数"] >= 200
    步骤["数据充足"] = int(m.sum())

    m &= F["上市天数"] >= 最少上市天数
    步骤["非次新"] = int(m.sum())

    if 剔除ST:
        m &= F["ST"] == 0
        步骤["非ST"] = int(m.sum())

    m &= F["可交易"] == 1
    步骤["未停牌"] = int(m.sum())

    # 市值：剔除最小 30%（壳价值污染）
    mv = F.loc[m, "流通市值"]
    if len(mv) > 50:
        界 = mv.quantile(市值剔除分位)
        m &= F["流通市值"] > 界
        步骤["市值过关"] = int(m.sum())
        步骤["_市值分界亿"] = round(float(界) / 1e8, 2)

    # 流动性
    amt = F.loc[m, "日均成交额"]
    if len(amt) > 50:
        m &= F["日均成交额"] > amt.quantile(流动性剔除分位)
        步骤["流动性过关"] = int(m.sum())

    # 估值护栏：亏损剔除 + 最贵 20% 剔除
    m &= F["EP"] > 0
    步骤["盈利"] = int(m.sum())
    ep = F.loc[m, "EP"]
    if len(ep) > 50:
        m &= F["EP"] > ep.quantile(估值剔除分位)
        步骤["估值过关"] = int(m.sum())

    return F.index[m], 步骤


# ============================================================
# 打分：四组因子，截面排名 → 百分位 → 行业市值中性 → 等权合成
# ============================================================
def _百分位(s):
    return s.rank(pct=True)


def _中性化(s, 行业, 市值):
    """减去所属行业均值，再对 log 市值做一元回归取残差。"""
    x = s.copy()
    if 行业 is not None and 行业.notna().any():
        x = x - x.groupby(行业).transform("mean")
    lm = np.log(市值.replace(0, np.nan))
    ok = x.notna() & lm.notna()
    if ok.sum() > 30:
        b = np.polyfit(lm[ok], x[ok], 1)
        x = x - (b[0] * lm + b[1])
    return x


def 打分(F, 池):
    """返回 (综合分 Series, 各组分 DataFrame)"""
    f = F.loc[池]
    行业, 市值 = f["行业"], f["流通市值"]

    组 = {}
    # 质量：ROE 高、ROE 波动小、毛利率高
    组["质量"] = (_百分位(f["roe_ttm"]) * 0.5
                  + _百分位(-f["roe波动"]) * 0.25
                  + _百分位(f["gpm"]) * 0.25)
    # 红利：股息率高、连续分红年数多
    组["红利"] = (_百分位(f["股息率"]) * 0.7
                  + _百分位(f["分红年数"]) * 0.3)
    # 低波：波动率低、最大回撤浅
    组["低波"] = (_百分位(-f["波动率"]) * 0.6
                  + _百分位(f["最大回撤"]) * 0.4)
    # 估值：EP 高（便宜）
    组["估值"] = _百分位(f["EP"])

    分 = pd.DataFrame(组)
    中性 = pd.DataFrame({k: _中性化(分[k], 行业, 市值) for k in 分})
    # 默认等权合成，刻意不做权重寻优。
    # 权重开放给用户调，但要知道：拿回测结果去调权重就是过拟合 ——
    # 你会调出一条漂亮的历史曲线和一个未来不成立的策略。
    w = pd.Series({k: float(因子权重.get(k, 1.0)) for k in 中性.columns})
    if w.sum() <= 0:
        w = pd.Series(1.0, index=中性.columns)
    综合 = (中性 * w).sum(axis=1) / w.sum()
    return 综合, 分


# ============================================================
# 绝对门槛（锚在市场分布与无风险利率，不从回测里挑）
# ============================================================
def 合格标的(F, 池, D, 调仓日, 全市场ROE中位):
    f = F.loc[池]
    无风险 = D.取无风险利率(调仓日) / 100.0

    # 门槛全部锚在市场分布和无风险利率上，不从回测里挑参数。
    # 每一条都可以在 config.json 里单独关掉 —— 但关掉之前先想清楚：
    # 「股息率高于国债」这条在 2011 年只有 11 只股票通过（当时 10 年国债 4.02%），
    # 是历史上最卡脖子的一条。放松它会让可选范围大增，也会让「红利」两个字失去意义。
    倍 = float(门槛开关.get("股息倍数", 1.0))
    门槛 = {}
    if 门槛开关.get("ROE", True):
        门槛["ROE高于历史中位"] = f["roe_ttm"] > 全市场ROE中位
    if 门槛开关.get("股息", True):
        门槛[f"股息率高于国债x{倍:g}"] = f["股息率"] > 无风险 * 倍
    if 门槛开关.get("波动", True):
        门槛[f"波动率低于{波动率门槛分位*100:.0f}分位"] = (
            f["波动率"] < f["波动率"].quantile(波动率门槛分位))
    if 门槛开关.get("EP", True):
        门槛["EP为正"] = f["EP"] > 0

    全过 = pd.Series(True, index=f.index)
    明细 = {}
    for k, v in 门槛.items():
        v = v.fillna(False)
        明细[k] = int(v.sum())
        全过 &= v
    if not 门槛:
        明细["（未启用任何绝对门槛）"] = int(len(f))
    明细["_无风险利率%"] = round(无风险 * 100, 2)
    明细["_ROE中位门槛"] = round(float(全市场ROE中位), 2)
    return f.index[全过], 明细


# ============================================================
# 权重：波动率倒数 + 单票上限 + 单行业上限
# ============================================================
def 定权重(F, 选中, 单票=单票上限, 行业上限=单行业上限):
    if len(选中) == 0:
        return pd.Series(dtype="float64")
    f = F.loc[选中]
    w = 1.0 / f["波动率"].replace(0, np.nan)
    w = w.fillna(w.median()).clip(lower=1e-9)
    w = w / w.sum()

    行业 = f["行业"].fillna("未知")
    for _ in range(50):
        改 = False
        # 单票上限
        超 = w > 单票 + 1e-9
        if 超.any():
            余 = (w[超] - 单票).sum()
            w[超] = 单票
            可加 = ~超
            if 可加.any() and w[可加].sum() > 0:
                w[可加] += 余 * w[可加] / w[可加].sum()
            改 = True
        # 单行业上限
        行业和 = w.groupby(行业).transform("sum")
        超行业 = 行业和 > 行业上限 + 1e-9
        if 超行业.any():
            for ind in 行业[超行业].unique():
                sel = 行业 == ind
                缩 = 行业上限 / w[sel].sum()
                余 = w[sel].sum() - 行业上限
                w[sel] *= 缩
                其他 = ~sel
                if 其他.any() and w[其他].sum() > 0:
                    w[其他] += 余 * w[其他] / w[其他].sum()
            改 = True
        if not 改:
            break
    return (w / w.sum()).sort_values(ascending=False)


# ============================================================
# 持仓数：资金自适应，不做回测寻优
# ============================================================
单笔最小金额 = 0.0      # 0 = 不限制（由 config.json 注入）
因子权重 = {"质量": 1.0, "红利": 1.0, "低波": 1.0, "估值": 1.0}


def 选股(F, 综合分, 合格, 资金, 上期N=None):
    """
    价格只做可行性过滤，绝不做选股因子 —— 顺序很要紧：
      1. 先按综合分把合格标的排好序
      2. 再从高分往下，只留「一手买得起」的
      3. N 由资金决定：找最大的 N，使得买得起的标的数 >= N

    返回 (选中 Index, N, 被价格挡掉的合格标的数, 是否补足)

    早先的写法是先取前 N 名再看买不买得起，结果第 1 名买不起就整期空仓，
    合成数据上跑出中位持仓 0 只。顺序反了。
    """
    补足 = False
    if len(合格) > 0:
        候选 = 综合分.reindex(合格).dropna().sort_values(ascending=False).index
    else:
        候选 = 综合分.sort_values(ascending=False).index
        补足 = True          # 无人达标，退而按分数取，界面上要标出来

    if len(候选) == 0 or 资金 <= 0:
        return pd.Index([]), 0, 0, 补足

    一手 = (F.loc[候选, "真实价"] * 100).values
    可行 = np.isfinite(一手) & (一手 > 0)

    上限N = int(np.clip(len(候选), 1, 持仓上限))
    if 上期N:
        上限N = min(上限N, max(1, int(上期N * 换手变化上限)))

    # 成本上限：每仓金额不能低于「单笔最小金额」。
    # 早先只按「买得起」找最大的 N，结果 2500 元被摊成 8 只、每仓 280 元，
    # 而佣金有 5 元下限 —— 每笔 5/280 = 1.8%，一年月调仓吃掉 7.2%，
    # 把 11.9% 的毛收益砍成 4.67%。分散是有价值的，但不是免费的。
    # 这里让用户用「单笔最小金额」直接表达他愿意为分散付多少手续费。
    if 单笔最小金额 > 0:
        上限N = max(1, min(上限N, int(资金 // 单笔最小金额)))

    for N in range(上限N, 0, -1):
        预算 = 资金 / N
        买得起 = 候选[可行 & (一手 <= 预算)]
        if len(买得起) >= N:
            挡掉 = len(候选) - len(买得起)
            if 上期N:
                N = max(N, 1)
            return 买得起[:N], N, 挡掉, 补足

    # 连一只都撑不起目标权重：退而求其次，买最贵但仍买得起的那只
    买得起 = 候选[可行 & (一手 <= 资金)]
    if len(买得起):
        return 买得起[:1], 1, len(候选) - len(买得起), 补足
    return pd.Index([]), 0, len(候选), 补足


# ============================================================
# 可成交性：T+1 / 涨跌停 / 停牌 / 一字板
# ============================================================
def 可买(D, code, i):
    """调仓日 i 能否买入：未停牌、非涨停开盘、非一字板"""
    if D.可交易.iat[i, D.可交易.columns.get_loc(code)] != 1:
        return False
    j = D.收盘.columns.get_loc(code)
    o = D.开盘.iat[i, j]
    if not np.isfinite(o) or o <= 0:
        return False
    if D.一字板.iat[i, j] == 1:
        return False                       # 一字板，买不到
    if i > 0:
        pc = D.收盘.iat[i - 1, j]
        if np.isfinite(pc) and pc > 0:
            涨 = o / pc - 1
            if 涨 >= 涨停阈值[板块(code, D.ST.iat[i, j] == 1, D.交易日[i])]:
                return False               # 涨停开盘，买不到
    return True


def 可卖(D, code, i):
    if D.可交易.iat[i, D.可交易.columns.get_loc(code)] != 1:
        return False
    j = D.收盘.columns.get_loc(code)
    o = D.开盘.iat[i, j]
    if not np.isfinite(o) or o <= 0:
        return False
    if D.一字板.iat[i, j] == 1:
        return False                       # 一字板，卖不掉
    if i > 0:
        pc = D.收盘.iat[i - 1, j]
        if np.isfinite(pc) and pc > 0:
            跌 = o / pc - 1
            if 跌 <= -涨停阈值[板块(code, D.ST.iat[i, j] == 1, D.交易日[i])]:
                return False               # 跌停开盘，卖不掉
    return True


# ============================================================
# 成本
# ============================================================
def 买入成本(金额):
    return (max(佣金最低, 金额 * 佣金费率)
            + 金额 * 过户费率 + 金额 * 滑点率)


def 卖出成本(金额):
    return (max(佣金最低, 金额 * 佣金费率) + 金额 * 印花税率
            + 金额 * 过户费率 + 金额 * 滑点率)


def 调仓日历(交易日, 频率="月"):
    s = pd.Series(交易日, index=pd.to_datetime(交易日))
    规则 = {"月": "ME", "季": "QE", "半年": "2QE", "年": "YE"}[频率]
    return list(s.resample(规则).last().dropna().values)
