# -*- coding: utf-8 -*-
"""
多进程下载的工作函数
====================
单独放一个文件，是因为 Windows 的多进程用 spawn 方式启动，
子进程会重新 import 这个模块，函数必须在模块顶层才能被正确传递。

每个子进程独立登录 Baostock（各自一条 socket 连接），
主进程只负责收结果、写数据库，避免并发写 SQLite 冲突。

关于重试策略（这一版重写过，有实测依据）：
  上一版一遇到报错就 logout + login 重建连接，实测 8.34 秒/只，
  比不重连时的 4.2 秒/只慢了一倍，而且有的股票重连三次仍然失败
  （sz.002576 跑了 72.1 秒后失败）。重连救不回来，说明问题不是
  「本地连接死了」而是「服务端在限流」—— 重连反而是额外两次请求
  打在已经限流你的服务器上，越重连越糟。
  所以改成：前几次只退避重试（服务端喘口气就好），
  只有最后一次才重建连接（应付真正掉线的会话）。
  退避时间拉长并加随机抖动，避免 4 个进程卡在同一拍上一起重试。
"""

import time
import random
import io
import contextlib

_LOGGED_IN = False

K字段 = ("date,code,open,high,low,close,volume,amount,"
         "turn,tradestatus,pctChg,isST")

# 每次尝试失败后等多久（秒）。最后一次才重建连接。
退避表 = (2.0, 5.0, 10.0)


登录退避 = (2.0, 5.0, 10.0, 20.0, 30.0)


def 子进程登录(强制=False):
    """登录 Baostock。成功返回 True，失败返回 False —— 绝不抛异常。

    为什么绝不抛：这个函数是 multiprocessing.Pool 的 initializer。
    在 initializer 里抛异常会让子进程当场死掉，而 Pool 会立刻重建一个新的，
    新的再登录再失败再死 —— 变成一个不停重建进程、不停发登录请求的死循环，
    正好砸在限流你的服务器上，越修越糟。（上一版就是这么错的，
    屏幕上出现 SpawnPoolWorker-5 而并发只有 4，就是这个循环的痕迹。）
    登录失败是限流导致的临时状态，退避重试就好，不该要了进程的命。
    """
    global _LOGGED_IN
    import baostock as bs
    if _LOGGED_IN and not 强制:
        return True
    if 强制:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                bs.logout()
        except Exception:
            pass
        _LOGGED_IN = False

    for i, 等 in enumerate(登录退避 + (None,)):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                lg = bs.login()
            if getattr(lg, "error_code", "0") == "0":
                _LOGGED_IN = True
                return True
        except Exception:
            pass
        if 等 is None:
            break
        time.sleep(等 * (0.7 + 0.6 * random.random()))
    _LOGGED_IN = False
    return False


def 初始化子进程():
    """Pool 的 initializer。错开各进程的首次登录，避免 4 个进程同时打过去
    形成一记齐射；登录不上也不抛异常，留着让每个任务自己再试。"""
    time.sleep(random.random() * 3.0)
    try:
        子进程登录()
    except Exception:
        pass


def _读结果集(rs):
    if rs.error_code != "0":
        raise RuntimeError(f"baostock {rs.error_code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return rows, rs.fields


def 取日线(参数):
    """
    参数 = (code, 起始日期, 结束日期)
    返回 (code, rows, fields, 错误, 耗时秒)
    失败不抛异常，返回错误字符串，让主进程记录后继续。
    rows 为空列表时主进程会判为「空表」并安排重下，不会当成功。
    """
    code, start, end = 参数
    import baostock as bs
    t0 = time.time()
    if not 子进程登录():
        # 连登录都被限流了，拿死连接去查没有意义。
        # 返回失败让主进程标记，下次重跑会自动重试这只。
        return (code, None, None,
                "登录失败（服务端限流），本轮跳过，重跑时会自动补",
                time.time() - t0)
    err = None
    总次数 = len(退避表) + 1

    for 第几次 in range(总次数):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rs = bs.query_history_k_data_plus(
                    code, K字段, start_date=start, end_date=end,
                    frequency="d", adjustflag="1")          # 1 = 后复权
                rows, fields = _读结果集(rs)
            return (code, rows, fields, None, time.time() - t0)
        except Exception as e:
            噪音 = buf.getvalue().strip().replace("\n", " ")[:120]
            err = f"{type(e).__name__}: {e}"
            if 噪音:
                err = f"{err} | {噪音}"
            if 第几次 >= len(退避表):
                break
            # 退避 + 抖动：别让 4 个进程卡在同一拍上一起重试
            time.sleep(退避表[第几次] * (0.7 + 0.6 * random.random()))
            # 只有最后一次重试前才重建连接 —— 前面几次重连只会加重限流
            if 第几次 == len(退避表) - 1:
                try:
                    子进程登录(强制=True)
                except Exception as e2:
                    err = f"{err} / 重登失败: {e2}"
    return (code, None, None, err, time.time() - t0)


def 取分红(参数):
    """
    参数 = (code, 年份列表)
    Baostock 的分红接口是按 股票+年份 查询的，这里把一只股票的所有年份
    在同一个子进程里跑完，省掉反复调度的开销。
    返回 (code, 记录列表, 错误, 耗时秒)
    记录 = (code, 年份, 公告日, 每股税前现金股息, 除权日, 登记日)
    """
    code, 年份列表 = 参数
    import baostock as bs
    t0 = time.time()
    if not 子进程登录():
        return (code, [], "登录失败（服务端限流），重跑时会自动补", time.time() - t0)
    out = []
    最后错误 = None

    for y in 年份列表:
        for 第几次 in range(2):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rs = bs.query_dividend_data(code=code, year=str(y),
                                                yearType="report")
                    rows, fields = _读结果集(rs)
                idx = {n: k for k, n in enumerate(fields)}

                def g(row, *候选):
                    for c in 候选:
                        if c in idx:
                            v = row[idx[c]]
                            if v not in (None, "", "-"):
                                return v
                    return None

                for row in rows:
                    现金 = g(row, "dividCashPsBeforeTax", "dividCashPsAfterTax")
                    try:
                        现金 = float(现金) if 现金 is not None else None
                    except Exception:
                        现金 = None
                    out.append((
                        code, f"{y}1231",
                        g(row, "dividPlanAnnounceDate", "dividPlanDate"),
                        现金,
                        g(row, "dividOperateDate"),
                        g(row, "dividRegistDate"),
                    ))
                break
            except Exception as e:
                最后错误 = f"{type(e).__name__}: {e}"
                time.sleep(0.8 * (第几次 + 1))

    return (code, out, (最后错误 if not out and 最后错误 else None),
            time.time() - t0)
