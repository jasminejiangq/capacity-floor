# -*- coding: utf-8 -*-
"""
WRDS 连接器（不依赖官方 wrds 包）
=================================
为什么不用官方 `wrds` 包：
  它把依赖钉死成 pandas<2.3,>=2.2。在 Python 3.14 上，pandas 2.2.x 没有
  预编译包，pip 只能从源码编译，而编译需要 Visual Studio C++ 工具链
  （几个 GB）。为了一个薄封装装一套编译器，不划算。

官方包真正做的事就是：连一个 PostgreSQL，然后把查询结果转成 DataFrame。
这个文件做同样的事，但驱动是可替换的，按「越不需要编译越优先」排序：

    1. psycopg  (v3)     —— C 扩展，最快，但要有对应 Python 版本的轮子
    2. psycopg2-binary   —— 同上
    3. pg8000            —— 纯 Python，任何 Python 版本都能装，永不需要编译

只要三个里有一个能装上，就能用。pg8000 是保底，它不可能失败。

⚠️ 数据合规：WRDS 数据不可再分发。这个模块不缓存、不落盘任何查询结果。
   你自己拉数时，原始文件只放 data/us/（已在 .gitignore 里）。
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

import os
import getpass

主机 = "wrds-pgdata.wharton.upenn.edu"
端口 = 9737
库名 = "wrds"


def _建连接(用户名, 密码):
    """按优先级尝试三个驱动，返回 (连接对象, 驱动名)。"""
    错误 = []

    # ---- 1. psycopg v3 ----
    try:
        import psycopg
        return psycopg.connect(host=主机, port=端口, dbname=库名,
                               user=用户名, password=密码,
                               sslmode="require"), "psycopg(v3)"
    except ImportError:
        错误.append("psycopg 未安装")
    except Exception as e:
        错误.append(f"psycopg 连接失败: {e}")

    # ---- 2. psycopg2 ----
    try:
        import psycopg2
        return psycopg2.connect(host=主机, port=端口, dbname=库名,
                                user=用户名, password=密码,
                                sslmode="require"), "psycopg2"
    except ImportError:
        错误.append("psycopg2 未安装")
    except Exception as e:
        错误.append(f"psycopg2 连接失败: {e}")

    # ---- 3. pg8000（纯 Python，保底）----
    try:
        import ssl
        import pg8000.dbapi
        ctx = ssl.create_default_context()
        return pg8000.dbapi.connect(user=用户名, password=密码, host=主机,
                                    port=端口, database=库名,
                                    ssl_context=ctx), "pg8000(纯Python)"
    except ImportError:
        错误.append("pg8000 未安装")
    except Exception as e:
        错误.append(f"pg8000 连接失败: {e}")

    raise RuntimeError(
        "三个 PostgreSQL 驱动都不可用。\n  " + "\n  ".join(错误) +
        "\n\n请先双击 10_修复WRDS安装.bat，它会自动挑一个能装的。")


class 连接:
    """极简 WRDS 连接。用法：

        from wrds_conn import 连接
        db = 连接()                      # 会问用户名密码
        df = db.查询("SELECT * FROM crsp.msf LIMIT 5")
        db.关闭()
    """

    def __init__(self, 用户名=None, 密码=None, 静默=False):
        self.用户名 = (用户名 or os.environ.get("WRDS_USER")
                       or input("WRDS 用户名: ").strip())
        pwd = (密码 or os.environ.get("WRDS_PASS")
               or getpass.getpass("WRDS 密码（输入时不显示）: "))
        if not 静默:
            print(f"  正在连接 {主机}:{端口} …")
            print("  第一次连接会收到 Duo 推送，请在手机上点确认。")
        self.conn, self.驱动 = _建连接(self.用户名, pwd)
        if not 静默:
            print(f"  ✓ 已连接（驱动：{self.驱动}）")

    def 查询(self, sql, 参数=None):
        """执行 SQL，返回 pandas DataFrame。"""
        import pandas as pd
        cur = self.conn.cursor()
        try:
            cur.execute(sql, 参数 or ())
            列 = [d[0] for d in cur.description] if cur.description else []
            行 = cur.fetchall() if cur.description else []
            return pd.DataFrame(行, columns=列)
        finally:
            cur.close()

    def 列出库(self):
        """返回我有权限访问的 schema 列表。"""
        df = self.查询("""
            SELECT DISTINCT table_schema
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog','information_schema')
            ORDER BY 1
        """)
        return df.iloc[:, 0].tolist() if len(df) else []

    def 列出表(self, 库):
        df = self.查询("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s ORDER BY 1
        """ if self.驱动 != "pg8000(纯Python)" else """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s ORDER BY 1
        """, (库,))
        return df.iloc[:, 0].tolist() if len(df) else []

    def 有没有这张表(self, 库, 表):
        df = self.查询("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema=%s AND table_name=%s
        """, (库, 表))
        return bool(len(df) and int(df.iloc[0, 0]) > 0)

    def 关闭(self):
        try:
            self.conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    db = 连接()
    print()
    库 = db.列出库()
    print(f"  可访问 {len(库)} 个 schema，其中相关的：")
    print("   ", [x for x in 库 if any(k in x for k in ("crsp", "comp", "ff"))][:20])
    db.关闭()
