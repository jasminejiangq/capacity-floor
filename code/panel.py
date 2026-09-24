# -*- coding: utf-8 -*-
"""
控制台 —— 本地网页界面
=====================
双击 05_控制台.bat 打开。它做三件事：

  1. 让你改参数，并且在你改的当下就看到代价（成本预估实时更新）
  2. 一键跑回测 / 一键今日选股，日志实时滚动
  3. 把最近一次回测结果摆在旁边，改完参数能立刻对比

只监听 127.0.0.1，外网访问不到。不联网、不上传任何东西。
"""
import os, sys, json, threading, subprocess, webbrowser, socket, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

这里 = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(这里)
OUT = os.path.join(ROOT, "output")
sys.path.insert(0, 这里)
import settings as S

任务 = {"运行中": False, "名称": "", "日志": [], "返回码": None, "开始": 0}
锁 = threading.Lock()


def 推日志(行):
    with 锁:
        任务["日志"].append(行.rstrip("\n"))
        if len(任务["日志"]) > 1200:
            del 任务["日志"][:400]


def 跑脚本(名称, 脚本, 参数=None):
    if 任务["运行中"]:
        return False
    with 锁:
        任务.update({"运行中": True, "名称": 名称, "日志": [], "返回码": None,
                     "开始": time.time()})

    def 干():
        try:
            py = sys.executable
            cmd = [py, os.path.join(这里, 脚本)] + (参数 or [])
            env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                       XUANGU_NO_PAUSE="1")
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=env,
                                 text=True, encoding="utf-8", errors="replace",
                                 bufsize=1)
            for line in p.stdout:
                推日志(line)
            p.wait()
            with 锁:
                任务["返回码"] = p.returncode
        except Exception as e:
            推日志(f"[启动失败] {e}")
            with 锁:
                任务["返回码"] = -1
        finally:
            with 锁:
                任务["运行中"] = False
    threading.Thread(target=干, daemon=True).start()
    return True


def 读json(名):
    p = os.path.join(OUT, 名)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _只披露(条):
    """有些验收项没有门槛，只是「必须如实摆出来」，不该计入达标分母。"""
    return "如实告知" in str(条.get("要求", "")) or "无门槛" in str(条.get("项", ""))


def 回测摘要():
    bt = 读json("回测结果.json")
    if not bt:
        return None
    g = bt.get("全程", {})
    v = bt.get("验收", {})
    # 验收在 JSON 里是 {"逐条": [ {项,达标,实际,要求}, ... ]}，
    # 早先这里当成「字典的字典」去遍历，于是永远数出 0/0。
    条 = v.get("逐条") if isinstance(v, dict) else None
    if not isinstance(条, list):
        条 = [x for x in v.values() if isinstance(x, dict)] if isinstance(v, dict) else []
    return {
        "起": g.get("起"), "止": g.get("止"),
        "年化": g.get("年化"), "最大回撤": g.get("最大回撤"),
        "夏普": g.get("夏普"), "月胜率": g.get("月胜率"),
        "最差连续12个月": g.get("最差连续12个月"),
        "Calmar": g.get("Calmar"),
        # 「最差连续12个月」那条是只披露、无门槛的，不进达标分母
        "达标": sum(1 for x in 条 if x.get("达标") and not _只披露(x)),
        "总条": sum(1 for x in 条 if not _只披露(x)),
        "验收": [{"项": x.get("项", ""), "达标": x.get("达标"),
                  "实际": x.get("实际"), "要求": x.get("要求"),
                  "只披露": _只披露(x)} for x in 条],
        "配置": bt.get("配置", {}),
        "运气分位": (bt.get("运气分布") or {}).get("实际分位"),
    }


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, HTML, "text/html; charset=utf-8")
        if u.path == "/api/config":
            cfg = S.读配置()
            return self._send(200, json.dumps(
                {"配置": cfg, "警告": S.警告, "成本": S.成本预估(cfg),
                 "回测": 回测摘要(), "选股": 读json("今日选股.json")},
                ensure_ascii=False))
        if u.path == "/api/cost":
            q = parse_qs(u.query)
            try:
                cfg = json.loads(q.get("cfg", ["{}"])[0])
            except Exception:
                cfg = {}
            merged = S._校验(S._合并(S.默认配置, cfg))
            out = {"警告": list(S.警告), "档位": {}}
            for 换手 in (0.15, 0.25, 0.5):
                out["档位"][f"{int(换手*100)}%"] = S.成本预估(merged, 换手)
            out["成本"] = out["档位"]["25%"]
            return self._send(200, json.dumps(out, ensure_ascii=False))
        if u.path == "/api/status":
            with 锁:
                st = {"运行中": 任务["运行中"], "名称": 任务["名称"],
                      "返回码": 任务["返回码"],
                      "用时": int(time.time() - 任务["开始"]) if 任务["开始"] else 0,
                      "日志": 任务["日志"][-260:]}
            return self._send(200, json.dumps(st, ensure_ascii=False))
        if u.path == "/api/results":
            return self._send(200, json.dumps(
                {"回测": 回测摘要(), "选股": 读json("今日选股.json")},
                ensure_ascii=False))
        return self._send(404, json.dumps({"错": "没有这个地址"}, ensure_ascii=False))

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8") if n else "{}"
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        if u.path == "/api/config":
            try:
                cfg = S.写配置(data.get("配置", {}))
                return self._send(200, json.dumps(
                    {"ok": True, "配置": cfg, "警告": S.警告,
                     "成本": S.成本预估(cfg)}, ensure_ascii=False))
            except Exception as e:
                return self._send(200, json.dumps(
                    {"ok": False, "错": str(e)}, ensure_ascii=False))
        if u.path == "/api/run":
            什么 = data.get("什么")
            映射 = {"回测": ("回测", "backtest.py"), "选股": ("今日选股", "pick.py"),
                    "验收": ("数据验收", "audit_data.py"),
                    "更新": ("每日更新", "update_db.py"),
                    "持仓": ("我的持仓分析", "portfolio.py")}
            if 什么 not in 映射:
                return self._send(200, json.dumps({"ok": False, "错": "不认识的任务"},
                                                  ensure_ascii=False))
            名, 脚本 = 映射[什么]
            ok = 跑脚本(名, 脚本)
            return self._send(200, json.dumps(
                {"ok": ok, "错": "" if ok else "已经有任务在跑了，等它跑完"},
                ensure_ascii=False))
        return self._send(404, json.dumps({"错": "没有这个地址"}, ensure_ascii=False))


HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股选股工具 · 控制台</title><style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--dim:#606a76;--line:#e3e6ea;
--accent:#2a78d6;--ok:#1baf7a;--warn:#d98324;--bad:#d94f4f;--soft:#f0f3f7}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#14171a;--card:#1c2025;--ink:#e8ebee;--dim:#9aa4b0;--line:#2b3138;
--soft:#232830}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,
"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
h1{font-size:19px;margin:8px 0 2px}
.sub{color:var(--dim);font-size:13px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:14px}
.card h2{font-size:14px;margin:0 0 10px;letter-spacing:.02em}
.row{display:flex;align-items:center;gap:10px;margin:7px 0}
.row label{flex:0 0 138px;font-size:13px;color:var(--dim)}
.row input[type=number],.row select{flex:1;min-width:0;padding:6px 8px;
border:1px solid var(--line);border-radius:6px;background:var(--bg);
color:var(--ink);font:inherit;font-size:13px}
.row .unit{flex:0 0 auto;color:var(--dim);font-size:12px}
.hint{font-size:12px;color:var(--dim);margin:2px 0 10px 148px;line-height:1.5}
@media(max-width:600px){.row label{flex:0 0 108px}.hint{margin-left:0}}
.chk{display:flex;align-items:center;gap:7px;font-size:13px;margin:5px 0}
.cost{background:var(--soft);border-radius:8px;padding:12px;margin-top:6px}
.cost .big{font-size:26px;font-weight:600;line-height:1.2}
.cost table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}
.cost td{padding:3px 0;color:var(--dim)}
.cost td:last-child{text-align:right;color:var(--ink);font-variant-numeric:tabular-nums}
button{font:inherit;font-size:13.5px;padding:8px 14px;border-radius:7px;
border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.pri{background:var(--accent);border-color:var(--accent);color:#fff}
button:disabled{opacity:.5;cursor:not-allowed}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
pre.log{background:#0f1215;color:#cfd6dd;border-radius:8px;padding:10px;
font:12px/1.55 ui-monospace,Consolas,monospace;height:300px;overflow:auto;
white-space:pre-wrap;word-break:break-all;margin:8px 0 0}
.kv{display:flex;justify-content:space-between;font-size:13px;padding:4px 0;
border-bottom:1px solid var(--line)}
.kv:last-child{border:0}
.kv b{font-variant-numeric:tabular-nums;font-weight:600}
.pass{color:var(--ok)}.fail{color:var(--bad)}.warn{color:var(--warn)}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;
background:var(--soft);color:var(--dim);margin-left:6px}
.warnbox{background:#fdf2e3;color:#7a4a08;border-radius:7px;padding:9px 11px;
font-size:12.5px;margin:8px 0}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .warnbox{
background:#3a2c14;color:#f0c98a}}
table.pick{width:100%;border-collapse:collapse;font-size:12.5px}
table.pick th,table.pick td{padding:5px 4px;border-bottom:1px solid var(--line);
text-align:right;font-variant-numeric:tabular-nums}
details.help{margin:2px 0 10px;font-size:12.5px}
details.help summary{cursor:pointer;color:var(--accent);list-style:none;
user-select:none;padding:2px 0}
details.help summary::-webkit-details-marker{display:none}
details.help summary::before{content:"？ 这些是什么意思";}
details.help[open] summary::before{content:"收起说明";}
details.help .body{color:var(--dim);line-height:1.75;background:var(--soft);
border-radius:8px;padding:10px 12px;margin-top:6px}
details.help .body b{color:var(--ink)}
details.help .body p{margin:0 0 8px}
details.help .body p:last-child{margin:0}
table.pick th:first-child,table.pick td:first-child,
table.pick th:nth-child(2),table.pick td:nth-child(2){text-align:left}
</style></head><body><div class="wrap">
<h1>A股选股工具 · 控制台</h1>
<div class="sub">改参数 → 看成本 → 跑回测 → 出清单。所有计算都在你自己电脑上，不联网。</div>
<div id="warns"></div>
<div class="grid">
<div>
  <div class="card"><h2>资金与成本</h2><details class="help"><summary></summary><div class="body">
  <p><b>可投入资金</b>：你真金白银打算放进这个策略的钱。它决定后面一切——
  能持几只、每只多少钱、手续费占多大比例。填你真实的数，别填理想的数。</p>
  <p><b>佣金费率</b>：券商按成交金额收的比例。但请注意——
  <b>单笔不到 3.3 万元时，这个费率完全不起作用</b>，你付的永远是下面那个最低值。</p>
  <p><b>单笔最低佣金</b>：绝大多数券商是 5 元。买 500 元收 5 元，
  实际费率就是 <b>1%</b>，是万1.5 的 67 倍。这是小资金最大的敌人。</p>
  <p><b>单笔最小金额</b>：<b>这是整个工具最关键的旋钮。</b>
  它规定「每只股票至少要投这么多钱」。设 800，就是说 2000 元最多分成 2 份。
  设得越大 → 持股越少、手续费占比越低、但越不分散。
  设成 0 = 不限制，工具会尽量多持几只，手续费最高。</p>
  </div></details>
    <div class="row"><label>可投入资金</label>
      <input type="number" id="初始资金" min="100" step="100"><span class="unit">元</span></div>
    <div class="row"><label>佣金费率</label>
      <input type="number" id="佣金费率万" min="0" max="30" step="0.1"><span class="unit">万分之</span></div>
    <div class="row"><label>单笔最低佣金</label>
      <input type="number" id="佣金最低" min="0" max="100" step="1"><span class="unit">元</span></div>
    <div class="hint">多数券商是 5 元。能谈到「免5」就填 0 —— 但那是灰色的，不写进协议，可能被调回。</div>
    <div class="row"><label>单笔最小金额</label>
      <input type="number" id="单笔最小金额" min="0" step="100"><span class="unit">元</span></div>
    <div class="hint"><b>这是最关键的旋钮。</b>它决定每仓多少钱，从而决定 5 元佣金占多大比例。
      填 0 = 不限制（会尽量多持几只，成本最高）。</div>
  </div>
  <div class="card"><h2>调仓与持仓</h2><details class="help"><summary></summary><div class="body">
  <p><b>调仓频率</b>：多久按规则重新选一次股、换一次仓。
  <b>成本几乎与频率成正比</b>——月调仓的手续费是季调仓的 3 倍。
  本项目实测：2500 元月调仓，一年手续费吃掉 7.2%；改成季调仓降到约 2.9%。</p>
  <p><b>持仓数上限</b>：最多同时持有几只。这只是天花板，
  实际持几只由「资金 ÷ 单笔最小金额」和「买得起几只」共同决定。</p>
  <p><b>回撤熔断</b>：当组合从最高点跌超过这个比例时，自动把仓位降到一半。
  听起来很安全，但本项目回测显示它<b>大幅降低收益</b>（年化从 8.85% 降到 -2.56%）——
  因为它往往在底部砍仓、在反弹时踏空。回测报告里两条曲线都会跑给你看。</p>
  </div></details>
    <div class="row"><label>调仓频率</label><select id="调仓频率">
      <option>月</option><option>季</option><option>半年</option><option>年</option></select></div>
    <div class="hint">成本几乎与频率成正比。月→季，交易成本直接降到三分之一。</div>
    <div class="row"><label>持仓数上限</label>
      <input type="number" id="持仓上限" min="1" max="100" step="1"><span class="unit">只</span></div>
    <div class="hint">实际持仓数由资金、单笔最小金额、和买得起的股票数共同决定，这里只是天花板。</div>
    <div class="row"><label>回撤熔断</label>
      <input type="number" id="熔断阈值%" min="0" max="100" step="5"><span class="unit">% 时降半仓</span></div>
  </div>
  <div class="card"><h2>股票池筛选</h2><details class="help"><summary></summary><div class="body">
  <p>这一组是「先把明显不该买的剔掉」，剔完剩下的才进入打分。</p>
  <p><b>剔除最小市值 30%</b>：A股小盘股长期有「壳价值」——公司再烂也值钱，
  因为可以卖壳借壳。这会污染因子。学术上（Liu-Stambaugh-Yuan 2019）
  标准做法就是剔掉最小的 30%。2024 年退市新规后壳价值在消退，但剔除仍然更稳。</p>
  <p><b>剔除低流动性 10%</b>：成交额太小的股票，你买卖会自己把价格打飞，
  滑点远超模型假设。</p>
  <p><b>剔除最贵的 20%</b>：按 EP（盈利÷市价）排序，剔掉最贵的那批。
  EP 是市盈率的倒数，高 EP = 便宜。论文显示 A 股用 EP 明显优于用市净率。</p>
  <p><b>最少上市天数 252</b>：约一年。次新股没有足够历史算波动率，
  而且上市初期定价常常不理性。</p>
  <p><b>剔除 ST</b>：ST 是「其他风险警示」，*ST 是「退市风险警示」。
  这类股票退市风险高、涨跌幅受限，散户几乎没有信息优势。</p>
  </div></details>
    <div class="row"><label>剔除最小市值</label>
      <input type="number" id="市值剔除分位%" min="0" max="90" step="5"><span class="unit">%</span></div>
    <div class="row"><label>剔除低流动性</label>
      <input type="number" id="流动性剔除分位%" min="0" max="90" step="5"><span class="unit">%</span></div>
    <div class="row"><label>剔除最贵的</label>
      <input type="number" id="估值剔除分位%" min="0" max="90" step="5"><span class="unit">%</span></div>
    <div class="row"><label>最少上市天数</label>
      <input type="number" id="最少上市天数" min="0" max="2000" step="1"><span class="unit">天</span></div>
    <label class="chk"><input type="checkbox" id="剔除ST"> 剔除 ST / *ST 股</label>
    <div class="row"><label>单行业上限</label>
      <input type="number" id="单行业上限%" min="5" max="100" step="5"><span class="unit">%</span></div>
  </div>
  <div class="card"><h2>因子权重 <span class="tag">默认等权，改之前请读下面那行</span></h2><details class="help"><summary></summary><div class="body">
  <p>四个因子各自衡量一件事，最后合成一个综合分给股票排序：</p>
  <p><b>质量</b>：赚钱能力强不强、稳不稳。看 ROE（净资产收益率，
  股东每投 100 元一年赚回多少）、毛利率、以及 ROE 的历史波动。</p>
  <p><b>红利</b>：分红大不大方、稳不稳定。看股息率（一年分红 ÷ 股价）
  和连续分红年数。股息率 5% 就是买 100 元股票一年分回 5 元。</p>
  <p><b>低波</b>：股价波动小不小、历史最大回撤浅不浅。
  学术上「低波动股票长期收益反而更高」是 A 股最稳健的异象之一。</p>
  <p><b>估值</b>：贵不贵。用 EP（盈利÷市价）。</p>
  <p>每个因子会先做<b>行业与市值中性化</b>——意思是不拿银行的 ROE 去比科技股的 ROE，
  只在同类里比，避免整个组合押在一个行业上。</p>
  </div></details>
    <div class="row"><label>质量（ROE等）</label><input type="number" id="w质量" min="0" max="5" step="0.1"></div>
    <div class="row"><label>红利（股息率）</label><input type="number" id="w红利" min="0" max="5" step="0.1"></div>
    <div class="row"><label>低波</label><input type="number" id="w低波" min="0" max="5" step="0.1"></div>
    <div class="row"><label>估值（EP）</label><input type="number" id="w估值" min="0" max="5" step="0.1"></div>
    <div class="hint"><b>拿回测结果去调权重就是过拟合</b>——你会调出一条漂亮的历史曲线，
      和一个未来不成立的策略。要改，请先想清楚理由，再用样本外那三年验证。</div>
  </div>
  <div class="card"><h2>绝对门槛</h2><details class="help"><summary></summary><div class="body">
  <p>上面的因子是<b>相对排序</b>（矮子里拔将军），这里是<b>绝对及格线</b>——
  达不到就不买，哪怕它是全市场最好的。这是防止「市场整体很贵时被迫买入」。</p>
  <p><b>ROE 高于历史中位</b>：赚钱能力至少要在历史平均水平之上。</p>
  <p><b>股息率高于 10 年国债</b>：<b>这条最卡脖子。</b>
  意思是「买股票拿到的分红，至少要比无风险的国债利息高」，否则不如买国债。
  2011 年国债 4.02%，全市场只有 11 只股票通过这一条。
  后面那个倍数可以放宽：填 0.8 就是「达到国债的 80% 即可」。
  放宽会让可选范围大增，但「红利」两个字也会变淡。</p>
  <p><b>波动率低于 70 分位</b>：只要波动率排在全市场前 70% 以内（越低越好）的。</p>
  <p><b>EP 为正</b>：公司必须是赚钱的。亏损股一律不买。</p>
  </div></details>
    <label class="chk"><input type="checkbox" id="g_ROE"> ROE 高于历史中位</label>
    <label class="chk"><input type="checkbox" id="g_股息"> 股息率高于 10 年国债 ×
      <input type="number" id="股息率门槛倍数" min="0" max="5" step="0.1"
        style="width:70px;padding:3px 6px;border:1px solid var(--line);
        border-radius:5px;background:var(--bg);color:var(--ink)"></label>
    <div class="hint">这条最卡脖子：2011 年国债 4.02%，全市场只有 11 只股票通过。
      调成 0.8 会放宽很多，但「红利」两个字也会变淡。</div>
    <label class="chk"><input type="checkbox" id="g_波动"> 波动率低于截面
      <input type="number" id="波动率门槛分位%" min="5" max="100" step="5"
        style="width:70px;padding:3px 6px;border:1px solid var(--line);
        border-radius:5px;background:var(--bg);color:var(--ink)"> % 分位</label>
    <label class="chk"><input type="checkbox" id="g_EP"> EP 为正（不买亏损股）</label>
  </div>
  <div class="card"><h2>回测设置</h2><details class="help"><summary></summary><div class="body">
  <p><b>回测起点</b>：从哪一天开始模拟。2010 年的数据要留给因子算窗口
  （比如 250 天波动率），所以起点设在 2011 年。</p>
  <p><b>样本外年数</b>：把最后 N 年<b>完全排除在设计之外</b>，
  用来检验策略是不是只是「事后诸葛亮」。
  如果样本外表现远差于全程，说明前面的好成绩是调参调出来的，不可信。</p>
  <p><b>运气模拟次数</b>：把整个回测用「随机选股」重跑 N 次，
  看你的选股规则到底比瞎选好多少。<b>这是全程最慢的一步</b>——
  40 次就是把回测跑 40 遍。试参数时调到 10～15，定稿时再用 40。</p>
  </div></details>
    <div class="row"><label>回测起点</label>
      <input type="text" id="回测起点" style="flex:1;padding:6px 8px;border:1px solid var(--line);
      border-radius:6px;background:var(--bg);color:var(--ink);font:inherit;font-size:13px"></div>
    <div class="row"><label>样本外年数</label>
      <input type="number" id="样本外年数" min="0" max="10" step="1"><span class="unit">年</span></div>
    <div class="row"><label>运气模拟次数</label>
      <input type="number" id="运气模拟次数" min="0" max="500" step="10"><span class="unit">次</span></div>
  </div>
</div>
<div>
  <div class="card"><h2>成本预估 <span class="tag">改上面任何一项，这里立刻变</span></h2>
    <div class="cost">
      <div>按初始资金估算的<b>年交易成本</b></div>
      <div class="big" id="年成本">—</div>
      <table><tbody id="成本表"></tbody></table>
    </div>
    <div class="hint" style="margin-left:0">本项目实测：2,500 元 + 月调仓 + 持仓 8 只
      → 年成本 7.2%，把 11.9% 的毛收益砍成 4.67%。成本占比会随账户变大而下降。</div>
    <div class="btns">
      <button class="pri" id="保存">保存参数</button>
      <button id="还原">恢复默认</button>
    </div>
  </div>
  <div class="card"><h2>运行</h2>
    <div class="btns">
      <button class="pri" id="跑回测">跑回测</button>
      <button id="跑选股">今日选股（约 1 分钟）</button>
      <button id="跑验收">数据验收</button>
      <button id="跑更新">更新数据（1–3 分钟）</button>
      <button id="跑持仓">分析我的持仓</button>
    </div>
    <div class="hint" style="margin-left:0" id="耗时提示"></div>
    <div class="hint" style="margin-left:0">改完参数<b>必须重跑回测</b>，否则旁边的成绩单对应的是旧参数。</div>
    <pre class="log" id="日志">（还没有运行任何任务）</pre>
  </div>
  <div class="card"><h2>最近一次回测</h2><div id="回测"></div></div>
  <div class="card"><h2>最近一次选股</h2><div id="选股"></div></div>
</div></div></div>
<script>
const $=id=>document.getElementById(id);
const pct=x=>x==null?'—':(x*100).toFixed(2)+'%';
let 当前={}, 计时=null;

function 填表(c){
  当前=c;
  const m=c['资金与成本'],t=c['调仓'],p=c['股票池'],w=c['因子权重'],g=c['绝对门槛'],b=c['回测'];
  $('初始资金').value=m['初始资金']; $('佣金费率万').value=(m['佣金费率']*10000).toFixed(2);
  $('佣金最低').value=m['佣金最低']; $('单笔最小金额').value=m['单笔最小金额'];
  $('调仓频率').value=t['调仓频率']; $('持仓上限').value=t['持仓上限'];
  $('熔断阈值%').value=Math.round(t['熔断阈值']*100);
  $('市值剔除分位%').value=Math.round(p['市值剔除分位']*100);
  $('流动性剔除分位%').value=Math.round(p['流动性剔除分位']*100);
  $('估值剔除分位%').value=Math.round(p['估值剔除分位']*100);
  $('最少上市天数').value=p['最少上市天数']; $('剔除ST').checked=!!p['剔除ST'];
  $('单行业上限%').value=Math.round(p['单行业上限']*100);
  $('w质量').value=w['质量']; $('w红利').value=w['红利'];
  $('w低波').value=w['低波']; $('w估值').value=w['估值'];
  $('g_ROE').checked=!!g['启用_ROE高于历史中位'];
  $('g_股息').checked=!!g['启用_股息率高于国债'];
  $('股息率门槛倍数').value=g['股息率门槛倍数'];
  $('g_波动').checked=!!g['启用_波动率低于分位'];
  $('波动率门槛分位%').value=Math.round(g['波动率门槛分位']*100);
  $('g_EP').checked=!!g['启用_EP为正'];
  $('回测起点').value=b['回测起点']; $('样本外年数').value=b['样本外年数'];
  $('运气模拟次数').value=b['运气模拟次数'];
}
function 收集(){
  const n=id=>parseFloat($(id).value)||0;
  return {'资金与成本':{'初始资金':n('初始资金'),'佣金费率':n('佣金费率万')/10000,
    '佣金最低':n('佣金最低'),'单笔最小金额':n('单笔最小金额'),
    '印花税率':当前['资金与成本']['印花税率'],'过户费率':当前['资金与成本']['过户费率'],
    '滑点率':当前['资金与成本']['滑点率']},
   '调仓':{'调仓频率':$('调仓频率').value,'持仓上限':n('持仓上限'),
    '换手变化上限':当前['调仓']['换手变化上限'],'熔断阈值':n('熔断阈值%')/100},
   '股票池':{'最少上市天数':n('最少上市天数'),'市值剔除分位':n('市值剔除分位%')/100,
    '流动性剔除分位':n('流动性剔除分位%')/100,'估值剔除分位':n('估值剔除分位%')/100,
    '剔除ST':$('剔除ST').checked,'单票上限':当前['股票池']['单票上限'],
    '单行业上限':n('单行业上限%')/100},
   '因子权重':{'质量':n('w质量'),'红利':n('w红利'),'低波':n('w低波'),'估值':n('w估值')},
   '绝对门槛':{'启用_ROE高于历史中位':$('g_ROE').checked,
    '启用_股息率高于国债':$('g_股息').checked,'股息率门槛倍数':n('股息率门槛倍数'),
    '启用_波动率低于分位':$('g_波动').checked,
    '波动率门槛分位':n('波动率门槛分位%')/100,'启用_EP为正':$('g_EP').checked},
   '回测':{'回测起点':$('回测起点').value,'样本外年数':n('样本外年数'),
    '运气模拟次数':n('运气模拟次数')}};
}
async function 刷成本(){
  const r=await fetch('/api/cost?cfg='+encodeURIComponent(JSON.stringify(收集())));
  const d=await r.json(); const c=d['成本'];
  $('年成本').textContent=c['年成本占比%']+'%';
  $('年成本').className='big '+(c['年成本占比%']>5?'fail':c['年成本占比%']>2.5?'warn':'pass');
  const g=d['档位'];
  $('成本表').innerHTML=
   `<tr><td>实际持仓数</td><td>${c['实际持仓数']} 只</td></tr>
    <tr><td>每仓金额</td><td>${c['每仓金额'].toLocaleString()} 元</td></tr>
    <tr><td>单笔佣金</td><td>${c['单笔佣金']} 元 ＝ 仓位的 ${c['单笔佣金占比%']}%</td></tr>
    <tr><td>每年调仓</td><td>${c['每年调仓次数']} 次</td></tr>
    <tr><td>每次调仓成本</td><td>${c['每期成本']} 元</td></tr>
    <tr><td>年成本（换手15%/25%/50%）</td><td>${g['15%']['年成本占比%']}% / ${g['25%']['年成本占比%']}% / ${g['50%']['年成本占比%']}%</td></tr>`;
  const w=d['警告']||[];
  $('warns').innerHTML=w.length?`<div class="warnbox">${w.map(x=>'⚠ '+x).join('<br>')}</div>`:'';
  // 回测耗时 ≈ 单次 × (2条主曲线 + 运气模拟次数)，单次 ≈ 调仓日数 × 1.1 秒
  const 每年={'月':12,'季':4,'半年':2,'年':1}[$('调仓频率').value]||4;
  const 年数=Math.max(1,2026-parseInt(($('回测起点').value||'2011').slice(0,4)));
  const 单次=Math.max(8,年数*每年*1.1), 次数=2+(parseFloat($('运气模拟次数').value)||0);
  const 秒=单次*次数, 分=Math.round(秒/60);
  $('耗时提示').innerHTML=`预计耗时 <b>${分<60?分+' 分钟':(秒/3600).toFixed(1)+' 小时'}</b>
    （${Math.round(年数*每年)} 个调仓日 × ${次数} 条曲线）。
    大头是「运气模拟」——它把整个回测重跑 ${次数-2} 次。
    想快速试参数，把运气模拟次数调到 10～15；定稿时再用 40。`;
}
function 画回测(b){
  if(!b){$('回测').innerHTML='<div class="hint" style="margin-left:0">还没跑过回测。</div>';return;}
  const 好=b['达标']>=b['总条']*0.7;
  let h=`<div class="kv"><span>验收</span><b class="${好?'pass':'fail'}">${b['达标']}/${b['总条']} 条达标</b></div>
   <div class="kv"><span>区间</span><b>${b['起']} ~ ${b['止']}</b></div>
   <div class="kv"><span>年化</span><b>${pct(b['年化'])}</b></div>
   <div class="kv"><span>最大回撤</span><b class="${b['最大回撤']<-0.3?'fail':''}">${pct(b['最大回撤'])}</b></div>
   <div class="kv"><span>夏普</span><b>${(b['夏普']||0).toFixed(2)}</b></div>
   <div class="kv"><span>月胜率</span><b>${pct(b['月胜率'])}</b></div>
   <div class="kv"><span>最差连续12个月</span><b class="fail">${pct(b['最差连续12个月'])}</b></div>
   <div class="kv"><span>优于随机选股的分位</span><b class="pass">${b['运气分位']==null?'—':(b['运气分位']*100).toFixed(0)+'%'}</b></div>`;
  const c=b['配置']||{};
  if(c['初始资金']!=null) h+=`<div class="hint" style="margin-left:0">该成绩对应参数：
    ${c['初始资金']}元 / 每${c['调仓频率']}调仓。若与上方当前参数不同，请重跑回测。</div>`;
  h+='<div style="margin-top:8px">'+(b['验收']||[]).map(v=>
    `<div class="kv"><span>${v['只披露']?'·':(v['达标']?'✓':'✗')} ${v['项']}</span>
     <b class="${v['只披露']?'warn':(v['达标']?'pass':'fail')}">${v['实际']??''}</b></div>`).join('')+'</div>';
  $('回测').innerHTML=h;
}
function 画选股(p){
  if(!p){$('选股').innerHTML='<div class="hint" style="margin-left:0">还没跑过今日选股。</div>';return;}
  const r=p['候选']||[];
  if(!r.length){$('选股').innerHTML=`<div class="warnbox">${p['交易日']} 一只都没选出来。
    门槛锚在市场分布和国债利率上，选不出来是正常且正确的结果，不是故障。</div>`;return;}
  $('选股').innerHTML=`<div class="hint" style="margin-left:0">${p['交易日']}　合格 ${p['合格数']} 只，
    资金 ${p['资金']} 元</div><table class="pick"><thead><tr><th>代码</th><th>名称</th>
    <th>现价</th><th>手数</th><th>金额</th><th>股息率</th><th>ROE</th><th>波动</th></tr></thead><tbody>`+
    r.map(x=>`<tr><td>${x['代码']}</td><td>${x['名称']||''}</td><td>${x['真实价']}</td>
    <td>${x['建议手数']}</td><td>${x['下单金额']}</td><td>${x['股息率%']}%</td>
    <td>${x['ROE%']}%</td><td>${x['年化波动%']}%</td></tr>`).join('')+'</tbody></table>';
}
async function 刷状态(){
  const d=await(await fetch('/api/status')).json();
  if(d['日志'] && d['日志'].length) {
    const el=$('日志'); const 贴底=el.scrollHeight-el.scrollTop-el.clientHeight<40;
    el.textContent=d['日志'].join('\n'); if(贴底) el.scrollTop=el.scrollHeight;
  }
  const 跑=d['运行中'];
  ['跑回测','跑选股','跑验收','跑更新','跑持仓','保存','还原'].forEach(i=>$(i).disabled=跑);
  if(跑){ $('跑回测').textContent=`${d['名称']} 运行中… ${d['用时']}s`; }
  else if(计时){ clearInterval(计时); 计时=null; $('跑回测').textContent='跑回测';
    const r=await(await fetch('/api/results')).json(); 画回测(r['回测']); 画选股(r['选股']); }
}
function 开始轮询(){ if(!计时) 计时=setInterval(刷状态,1200); 刷状态(); }
async function 跑(什么){
  const d=await(await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({什么})})).json();
  if(!d.ok){alert(d['错']);return;} 开始轮询();
}
$('保存').onclick=async()=>{
  const d=await(await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({配置:收集()})})).json();
  if(d.ok){填表(d['配置']); 刷成本(); $('保存').textContent='已保存 ✓';
    setTimeout(()=>$('保存').textContent='保存参数',1500);} else alert(d['错']);
};
$('还原').onclick=async()=>{
  if(!confirm('恢复成本项目验证过的默认参数？当前设置会被覆盖。'))return;
  const d=await(await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({配置:{}})})).json();
  if(d.ok){填表(d['配置']); 刷成本();}
};
$('跑回测').onclick=()=>跑('回测'); $('跑选股').onclick=()=>跑('选股');
$('跑验收').onclick=()=>跑('验收');
$('跑更新').onclick=()=>跑('更新'); $('跑持仓').onclick=()=>跑('持仓');
document.addEventListener('input',e=>{if(e.target.closest('.card'))刷成本();});
document.addEventListener('change',e=>{if(e.target.closest('.card'))刷成本();});
(async()=>{const d=await(await fetch('/api/config')).json();
  填表(d['配置']); 刷成本(); 画回测(d['回测']); 画选股(d['选股']); 刷状态();})();
</script></body></html>"""


def 空闲端口(起=8731):
    for p in range(起, 起 + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 起


if __name__ == "__main__":
    端口 = 空闲端口()
    地址 = f"http://127.0.0.1:{端口}/"
    srv = ThreadingHTTPServer(("127.0.0.1", 端口), H)
    print("=" * 62)
    print("   A股选股工具 · 控制台已启动")
    print("=" * 62)
    print(f"   浏览器地址：{地址}")
    print("   如果浏览器没有自动打开，把上面这行复制到地址栏。")
    print("   只监听本机，外网访问不到；不联网、不上传任何数据。")
    print()
    print("   用完直接关掉这个黑窗口就行。")
    print("=" * 62)
    try:
        webbrowser.open(地址)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已关闭。")
