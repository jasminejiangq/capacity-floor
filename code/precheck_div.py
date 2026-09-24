# -*- coding: utf-8 -*-
"""
分红数据预检（约 2-4 分钟）

为什么要单独跑这一步：
  上一轮建库时，分红表拉下来是 0 行 —— 有两个 bug（列名找错 + 失败时不打印，
  静默跳过）。两个都已经修了，但修完之后还没在真实网络上验证过。
  分红是「质量红利低波」里「红利」那一个因子的唯一原料，如果这里是空的，
  整个策略就塌了一根腿。
  而在完整建库流程里，分红排在日线后面 —— 意味着要先等 3 个多小时下完日线，
  才轮到它。万一还是失败，那 3 小时就白等了。
  所以先花 3 分钟单独验一次。验过了再启动全量，才叫踏实。

这个脚本只拉最近 2 个年报期，拉到的数据是真数据，会存进库，
全量建库时会自动跳过这 2 期，不会重复下载。
"""
import sys, os

这里 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 这里)

import build_db as B


def 主():
    B.bar("=")
    B.say("   分红数据预检")
    B.bar("=")
    B.say()

    c = B.open_db()

    before = c.execute("SELECT COUNT(*) FROM dividend").fetchone()[0]
    B.say(f"  开始前：dividend 表 {before:,} 行")
    B.say()

    B.任务_分红(c, "试运行")
    c.commit()

    after = c.execute("SELECT COUNT(*) FROM dividend").fetchone()[0]

    B.bar("=")
    B.say("   预检结论")
    B.bar("=")
    B.say(f"  dividend 表：{before:,} 行  →  {after:,} 行  （新增 {after-before:,}）")
    B.say()

    if after > before and after > 1000:
        B.say("  ✅ 通过。分红数据能正常入库，两个 bug 确实修好了。")
        B.say()
        # 抽样看几条，确认字段不是空的
        行 = c.execute(
            "SELECT code, plan_ann_date, cash_per10, total_share "
            "FROM dividend WHERE cash_per10 IS NOT NULL "
            "ORDER BY plan_ann_date DESC LIMIT 5").fetchall()
        if 行:
            B.say("  抽查 5 条（确认关键字段不是空的）：")
            B.say(f"    {'代码':<12}{'预案公告日':<14}{'每10股派现':>12}{'总股本':>18}")
            for r in 行:
                总 = f"{r[3]:,.0f}" if r[3] is not None else "—"
                派 = f"{r[2]:.4f}" if r[2] is not None else "—"
                B.say(f"    {str(r[0]):<12}{str(r[1]):<14}{派:>12}{总:>18}")
        else:
            B.say("  ⚠ 但 cash_per10 全是空的 —— 字段映射还有问题，先别跑全量。")
        B.say()
        B.say("  下一步：双击 02_build_database.bat，选全量，让它跑完。")
    else:
        B.say("  ❌ 没通过。分红还是拉不下来。")
        B.say()
        B.say("  上面的日志里应该有一行以 ✗ 开头的错误信息（修复之后不会再静默跳过了）。")
        B.say("  请把整个窗口的内容截图发给 Claude，先别启动全量建库 ——")
        B.say("  没有分红数据，红利因子做不出来，跑完也是白跑。")
    B.say()

    try:
        目录 = os.path.join(os.path.dirname(这里), "output")
        os.makedirs(目录, exist_ok=True)
        with open(os.path.join(目录, "分红预检日志.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(str(x) for x in B.日志))
        B.say("  日志已存到 output\\分红预检日志.txt")
    except Exception:
        pass
    c.close()


if __name__ == "__main__":
    try:
        主()
    except KeyboardInterrupt:
        print("\n  已中断。")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n  出错了：{e}")
    input("\n  按回车关闭。")
