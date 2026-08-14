"""离线单元测试：不碰 gh，不碰网络。python3 test_kit.py"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("sentinel", "sentinel.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))
    if not cond: fails.append(name)

# 1) 包号正则
check("P5", m.package_tag("认领件 P5：迁移") == "P5")
check("P12", m.package_tag("P12 新主线") == "P12")
check("XP3 不误伤", m.package_tag("XP3 不该匹配") is None)

# 2) label 覆盖 + 长标题关键词在 40 字之后（赫的疑点）
LONG = "认领件 P7：" + "填" * 45 + "尾部关键词落在四十字之后"
class FakeCfg(dict): pass
w = m.Sentinel.__new__(m.Sentinel)
w.cfg = {"subscriptions": [{"match": "尾部关键词", "events": "*", "label": "长尾"}]}
ev = w.mk("99", LONG, "issue_comment", "+1")
check("长标题订阅命中且 label 生效", "[长尾]" in ev["line"], ev["line"][:60])
check("订阅过滤同样命中", w.subscribed({"event":"issue_comment","number":"99","title":LONG}))

# 3) 无 label 时默认包号
w2 = m.Sentinel.__new__(m.Sentinel)
w2.cfg = {"subscriptions": [{"match": "*", "events": "*"}]}
ev2 = w2.mk("15", "认领件 P3：启动包装配器", "new_pr", "")
check("默认 P 标签", ev2["line"].startswith("[P3]") or "[P3]" in ev2["line"], ev2["line"][:50])

# 4) full_text：配了才拉正文、正文附在摘要行之后；没配的订阅一条 gh 都不调
w3 = m.Sentinel.__new__(m.Sentinel)
w3.cfg = {"subscriptions": [{"match": "#19", "events": "*", "full_text": True}]}
w3.fetch_comment_bodies = lambda num, k: "「tester」\n正文第一行\n正文第二行"
ev3 = w3.mk("19", "P5: 住户迁移", "pr_comment", "+1 (共5)", delta=1)
first = ev3["line"].split("\n")[0]
check("full_text 摘要行仍是单行铃声", "pr_comment" in first and "正文" not in first)
check("full_text 正文跟在摘要后", ev3["line"].split("\n", 1)[1].startswith("「tester」"))

w4 = m.Sentinel.__new__(m.Sentinel)
w4.cfg = {"subscriptions": [{"match": "*", "events": "*"}]}
w4.fetch_comment_bodies = lambda num, k: (_ for _ in ()).throw(AssertionError("不该拉正文"))
ev4 = w4.mk("16", "认领件 P4", "issue_comment", "+1 (共22)", delta=1)
check("未配 full_text 不拉正文", "\n" not in ev4["line"])

# 5) clip_body 保留换行、只截长度
clipped = m.clip_body("a\nb" * 1000)
check("clip_body 截断", len(clipped) <= m.FULLTEXT_MAX_CHARS and clipped.endswith("…"))
check("clip_body 保留换行", "\n" in clipped)

sys.exit(1 if fails else 0)
