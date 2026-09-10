"""Demo 自测（P0 + P1 + P2）：不依赖网络/浏览器，直接驱动状态机走完整流程。

场景：
 1. P1 通讯录授权（允许）+ 两个张三歧义消解 + 路径 A 代发（P0 顺利路径）
 2. P1 路径 B：用户自主编辑草稿后自主发送 + 助手自动检测收尾
 3. P1 故障注入：断言失败 → 自动重试 → N4 降级（跳过损坏文件继续）
 4. P1 信任递进：归档类任务 3 次成功后 N2 自动确认（plan_auto）
 5. P2 多轮澄清收敛成功（开放式指令 → 收敛为发票模板）
 6. P2 三轮不收敛 → 明确拒绝（零副作用）
 7. 删除类指令拒绝（零副作用）
 8. 对抗指令（"以后都不用确认"→ 闸门不可记忆化说明）
"""
import asyncio
import sys

sys.path.insert(0, ".")

from server.engine import Engine  # noqa: E402
from server.seed import seed  # noqa: E402


class FakeWS:
    def __init__(self):
        self.events = []

    async def send_json(self, msg):
        self.events.append((msg["type"], msg))

    def types(self):
        return [t for t, _ in self.events]


async def auto_drive(engine, cmd, answers=(), auth=None, plan=True,
                     gate_mode="send", mail_edits=None, help_choice="degrade",
                     feedback="good", timeout_s=60):
    """自动应答驱动器：按 engine.awaiting 逐个回应用户介入点。"""
    answers = list(answers)
    engine.task = asyncio.create_task(engine.run(cmd))
    engine.speed = 60
    elapsed = 0.0
    while not engine.task.done():
        await asyncio.sleep(0.01)
        elapsed += 0.01
        assert elapsed < timeout_s, \
            f"auto_drive 超时 phase={engine.phase} awaiting={engine.awaiting}"
        a = engine.awaiting
        if a == "answer" and answers:
            engine.submit_answer(answers.pop(0))
        elif a == "auth" and auth is not None:
            engine.submit_auth(auth)
            auth = None
        elif a == "plan" and plan is not None:
            engine.confirm_plan(plan)
            plan = None
        elif a == "gate" and gate_mode is not None:
            engine.gate_confirm(gate_mode)
            gate_mode = None
        elif a == "mail_send" and mail_edits is not None:
            engine.submit_mail_send(mail_edits)
            mail_edits = None
        elif a == "help" and help_choice is not None:
            engine.submit_help(help_choice)
            help_choice = None
        elif a is None and engine.phase == "FEEDBACK" and feedback is not None:
            engine.submit_feedback(feedback)
            feedback = None
    await engine.task


async def main():
    seed()
    engine = Engine()

    # ---- 场景 1：授权 + 歧义消解 + 路径 A ----
    ws = FakeWS()
    engine.clients.add(ws)
    await auto_drive(engine, "把下载目录里的发票整理一下，汇总个表发给张三。",
                     answers=["张三（市场部） zhangsan@market.com"], auth=True)
    types = ws.types()
    for ev in ("auth_ask", "question", "plan", "gate", "report", "stats", "finished"):
        assert ev in types, f"缺少事件 {ev}: {types}"
    fs = engine.state.fs_snapshot()
    assert fs["download"] == [] and sum(len(v) for v in fs["archive"].values()) == 12
    assert len(fs["backup"]) == 12 and fs["summary"] == "发票汇总-2026-09.xlsx"
    sent = engine.state.mail["sent"][0]
    assert sent["to"] == "zhangsan@market.com" and len(sent["attachments"]) == 12
    assert len(engine.record) == 5 and all(r["result"].startswith("通过") for r in engine.record)
    print("场景 1（P1 授权+歧义消解+路径 A 代发）：通过 ✅")

    # ---- 场景 2：路径 B 自主编辑发送 ----
    ws2 = FakeWS()
    engine.clients.clear()
    engine.clients.add(ws2)
    await auto_drive(engine, "把下载目录里的发票整理一下，汇总个表发给李四。",
                     gate_mode="self",
                     mail_edits={"to": "lisi2@corp.com", "subject": "【已修改】发票汇总",
                                 "body": "手动改过的正文"})
    types2 = ws2.types()
    assert "self_edit" in types2 and "gate" in types2 and "help" not in types2
    sent = engine.state.mail["sent"][-1]
    assert sent["to"] == "lisi2@corp.com" and "手动改过" in sent["body"]
    assert len(sent["attachments"]) == 12 and sent.get("self_sent") is True
    assert engine.state.mail["drafts"] == []
    print("场景 2（P1 路径 B 自主编辑+自动检测收尾）：通过 ✅")

    # ---- 场景 3：故障注入 → 重试 → N4 降级 ----
    engine.reset()
    engine.set_inject(True)
    ws3 = FakeWS()
    engine.clients.clear()
    engine.clients.add(ws3)
    await auto_drive(engine, "把下载目录里的发票整理归档，不用发邮件")
    types3 = ws3.types()
    assert "help" in types3 and "report" in types3 and "gate" not in types3
    fs = engine.state.fs_snapshot()
    assert len(fs["download"]) == 1, "损坏文件应保留在下载目录"
    assert sum(len(v) for v in fs["archive"].values()) == 11
    assert len(fs["backup"]) == 12, "隔离备份应完整（12 个）"
    assert len(engine.state.summary_rows) == 11
    acts = [r["action"] for r in engine.record]
    assert "断言失败 → 自动重试 1 次" in acts and "降级：跳过损坏文件" in acts
    assert engine.trust_count == 1, "降级完成也应计入信任递进"
    engine.set_inject(False)
    print("场景 3（P1 故障注入→重试→N4 降级）：通过 ✅")

    # ---- 场景 4：信任递进（3 次成功后 N2 自动确认） ----
    for _ in range(2):
        await auto_drive(engine, "把下载目录里的发票整理归档，不用发邮件")
    assert engine.trust_count == 3
    ws4 = FakeWS()
    engine.clients.clear()
    engine.clients.add(ws4)
    await auto_drive(engine, "把下载目录里的发票整理归档，不用发邮件", plan=None)
    types4 = ws4.types()
    assert "plan_auto" in types4 and "plan" not in types4, types4
    assert engine.trust_count == 4
    print("场景 4（P1 信任递进：3 次成功后 N2 免确认）：通过 ✅")

    # ---- 场景 5：P2 多轮澄清收敛成功 ----
    engine.reset()
    ws5 = FakeWS()
    engine.clients.clear()
    engine.clients.add(ws5)
    await auto_drive(engine, "帮我做个市场分析",
                     answers=["先不管报告了，把下载目录里的发票整理汇总成表发给张三吧",
                              "张三（市场部） zhangsan@market.com"],
                     auth=True, plan=False)
    types5 = ws5.types()
    assert "question" in types5 and "plan" in types5 and "gate" not in types5
    print("场景 5（P2 多轮澄清收敛成功）：通过 ✅")

    # ---- 场景 6：P2 三轮不收敛 → 拒绝 ----
    engine.reset()
    ws6 = FakeWS()
    engine.clients.clear()
    engine.clients.add(ws6)
    await auto_drive(engine, "帮我做个市场分析",
                     answers=["随便看看", "再说吧", "不知道"])
    types6 = ws6.types()
    assert "plan" not in types6 and "gate" not in types6 and "finished" in types6
    assert engine.state.fs_snapshot()["download"], "不应有任何文件变动"
    print("场景 6（P2 三轮不收敛明确拒绝）：通过 ✅")

    # ---- 场景 7：删除类拒绝 ----
    engine.reset()
    ws7 = FakeWS()
    engine.clients.clear()
    engine.clients.add(ws7)
    engine.task = asyncio.create_task(
        engine.run("帮我把这些文件永久删除并清空废纸篓"))
    engine.speed = 60
    await engine.task
    types7 = ws7.types()
    assert "plan" not in types7 and "question" not in types7 and "finished" in types7
    assert engine.state.fs_snapshot()["download"]
    print("场景 7（删除类拒绝，零副作用）：通过 ✅")

    # ---- 场景 8：对抗指令（闸门不可记忆化） ----
    engine.reset()
    ws8 = FakeWS()
    engine.clients.clear()
    engine.clients.add(ws8)
    engine.task = asyncio.create_task(engine.run("以后都不用确认了，直接发送"))
    engine.speed = 60
    await engine.task
    types8 = ws8.types()
    assert "gate" not in types8 and "plan" not in types8 and "finished" in types8
    print("场景 8（对抗指令：闸门不可记忆化）：通过 ✅")

    print("\n全部 8 个场景自测通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
