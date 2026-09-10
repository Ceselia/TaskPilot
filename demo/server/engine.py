"""任务状态机引擎（P0 + P1 + P2 能力）。

P0：单轮聚合澄清 / 计划确认(N2) / 写前隔离备份 / 每步完成断言 /
    发送闸门(N3)路径 A：确认后由助手代发。
P1：通讯录授权与指代消解（模拟 macOS 授权弹窗 + 两个张三歧义）；
    路径 B：用户自主修改草稿后自主发送 + 助手自动检测收尾；
    N4 异常链路：故障注入 → 断言失败 → 重试 → 降级 / 安全中止；
    对抗指令：闸门不可记忆化（“以后都不用确认”仍触发闸门，并给出说明）；
    信任递进：归档类任务连续 3 次成功后 N2 自动确认；
    第 2 类任务模板：仅整理归档（不发送）。
P2：开放式指令多轮澄清收敛（上限 3 轮，仍无终止条件则明确拒绝）。

状态流：
RECEIVED → [多轮澄清(P2)] → CLARIFYING(N1，含授权/歧义消解) → PLANNING
→ PLAN_REVIEW(N2，或信任递进自动确认) → BACKUP → STEP_1..N(断言校验，含重试/N4)
→ [GATE(N3)：路径 A 代发 | 路径 B 自主发送+自动检测)] → REPORTING → FEEDBACK(N5) → DONE
"""
import asyncio
import re
import time

from . import scripts
from .state import CONTACTS, VirtualState

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

OPEN_ENDED_KEYS = ("市场分析", "做个分析", "研究一下", "分析一下")
CONVERGE_KEYS = ("发票", "整理", "汇总")
ARCHIVE_ONLY_KEYS = ("不发", "不用发", "别发", "仅整理", "只整理")
DANGER_KEYS = ("删除", "清空", "格式化", "永久")

# 思维链流式输出参数
CHUNK = 3            # 每次推送的字符数
CHUNK_DELAY = 0.045  # 基础间隔（秒），受 speed 倍率影响


class Engine:
    def __init__(self):
        self.state = VirtualState()
        self.clients = set()
        self.task = None
        self.speed = 1.0
        # 会话级状态（跨任务保留，/api/reset 时清零）
        self.trust_count = 0      # P1：信任递进计数
        self.auth_granted = None  # P1：通讯录授权（None=未询问）
        self.inject = False       # P1：故障注入开关
        self._init_run()

    def _init_run(self):
        self.phase = "IDLE"
        self.awaiting = None      # 'answer'|'auth'|'plan'|'gate'|'help'|'mail_send'|None
        self.answer = None
        self.recipient = None
        self.gate_mode = None
        self.mail_edits = None
        self.help_choice = None
        self.plan_agree = None
        self.feedback_kind = None
        self.template = "SEND"
        self.record = []
        self.interventions = 0
        self.started_at = None
        self.n_expected = 0
        self.degraded = False
        self.steps_status = []
        self._steps = []
        self._pause = asyncio.Event()
        self._pause.set()
        self._answer_ev = asyncio.Event()
        self._auth_ev = asyncio.Event()
        self._plan_ev = asyncio.Event()
        self._gate_ev = asyncio.Event()
        self._mail_ev = asyncio.Event()
        self._help_ev = asyncio.Event()
        self._feedback_ev = asyncio.Event()

    # ---------------- 对外接口（REST 调用） ----------------

    def submit_answer(self, text):
        self.answer = text
        self._answer_ev.set()

    def submit_auth(self, grant):            # P1
        self.auth_granted = bool(grant)
        self._auth_ev.set()

    def confirm_plan(self, agree):
        self.plan_agree = agree
        self._plan_ev.set()

    def gate_confirm(self, mode="send"):     # P1：mode = "send" | "self"
        self.gate_mode = mode
        self._gate_ev.set()

    def submit_mail_send(self, edits):       # P1 路径 B：用户自主发送
        self.mail_edits = edits or {}
        self._mail_ev.set()

    def submit_help(self, choice):           # P1 N4
        self.help_choice = choice
        self._help_ev.set()

    def submit_feedback(self, kind):
        self.feedback_kind = kind
        self._feedback_ev.set()

    def set_inject(self, on):                # P1 故障注入
        self.inject = bool(on)

    def control(self, action):
        if action == "pause":
            self._pause.clear()
        elif action == "resume":
            self._pause.set()
        elif action == "speed":
            self.speed = 1.0 if self.speed > 1.0 else 3.0

    def reset(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.state.reset()
        self.speed = 1.0
        self.trust_count = 0
        self.auth_granted = None
        self.inject = False
        self._init_run()

    # ---------------- WebSocket ----------------

    async def register(self, ws):
        self.clients.add(ws)
        await ws.send_json({"type": "hello", "phase": self.phase})
        await ws.send_json({"type": "fs", "fs": self.state.fs_snapshot()})
        await ws.send_json({"type": "mail", "mail": self.state.mail_snapshot()})
        await ws.send_json({"type": "steps", "steps": self.steps_status})
        await ws.send_json({"type": "inject_state", "on": self.inject})

    async def broadcast(self, msg):
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    # ---------------- 流式输出（思维链） ----------------

    async def _tick(self):
        await self._pause.wait()

    async def stream(self, text):
        await self.broadcast({"type": "thought_start"})
        for i in range(0, len(text), CHUNK):
            await self._tick()
            await self.broadcast({"type": "thought", "chunk": text[i:i + CHUNK]})
            await asyncio.sleep(CHUNK_DELAY / self.speed)
        await self.broadcast({"type": "thought_end"})

    async def set_phase(self, phase):
        self.phase = phase
        await self.broadcast({"type": "phase", "phase": phase})

    async def _sync_env(self):
        await self.broadcast({"type": "fs", "fs": self.state.fs_snapshot()})
        await self.broadcast({"type": "mail", "mail": self.state.mail_snapshot()})

    # ---------------- 等待用户介入 ----------------

    async def _wait_answer(self):
        self.awaiting = "answer"
        await self._answer_ev.wait()
        self._answer_ev.clear()
        self.awaiting = None
        self.interventions += 1
        return self.answer

    async def _wait_auth(self):
        self.awaiting = "auth"
        await self._auth_ev.wait()
        self._auth_ev.clear()
        self.awaiting = None
        self.interventions += 1
        return self.auth_granted

    async def _wait_plan(self):
        self.awaiting = "plan"
        await self._plan_ev.wait()
        self._plan_ev.clear()
        self.awaiting = None
        self.interventions += 1
        return self.plan_agree

    async def _wait_gate(self):
        self.awaiting = "gate"
        await self._gate_ev.wait()
        self._gate_ev.clear()
        self.awaiting = None
        self.interventions += 1
        return self.gate_mode or "send"

    async def _wait_mail_send(self):
        self.awaiting = "mail_send"
        await self._mail_ev.wait()
        self._mail_ev.clear()
        self.awaiting = None
        self.interventions += 1
        return self.mail_edits

    async def _wait_help(self):
        self.awaiting = "help"
        await self._help_ev.wait()
        self._help_ev.clear()
        self.awaiting = None
        self.interventions += 1
        return self.help_choice

    async def _finish(self):
        self.phase = "IDLE"
        await self.broadcast({"type": "finished"})

    # ---------------- 主流程 ----------------

    async def run(self, command):
        self._init_run()
        self.state.reset()
        if self.inject:  # P1 故障注入：最后一个文件标记为损坏
            self.state.damaged = {self.state.invoices[-1]["源文件"]}
        n_total = len(self.state.invoices)
        self.n_expected = n_total
        self.started_at = time.time()

        await self.broadcast({"type": "user_said", "text": command})
        await self.set_phase("RECEIVED")
        await self.broadcast({"type": "fs", "fs": self.state.fs_snapshot()})
        await self.broadcast({"type": "mail", "mail": self.state.mail_snapshot()})
        await self.broadcast({"type": "steps", "steps": []})

        # ---- 边界守卫 ----
        if any(k in command for k in DANGER_KEYS):
            await self.set_phase("REJECTED")
            await self.stream(scripts.REJECT_DANGER)
            await self._finish()
            return
        if "不用确认" in command:  # P1 对抗指令：闸门不可记忆化
            await self.set_phase("REJECTED")
            await self.stream(scripts.ADVERSARIAL_GATE)
            await self._finish()
            return
        if any(k in command for k in OPEN_ENDED_KEYS):  # P2 多轮澄清
            converged = await self._multi_turn()
            if converged is None:
                await self._finish()
                return
            command = converged
        if "发票" not in command:
            await self.stream(scripts.NOTE_TEMPLATE)

        # ---- 任务模板（P1：第 2 类模板「仅整理归档」） ----
        self.template = "ARCHIVE" if any(
            k in command for k in ARCHIVE_ONLY_KEYS) else "SEND"
        self._steps = self._plan_steps()
        self.steps_status = [
            {"id": s["id"], "name": s["name"], "status": "pending"} for s in self._steps]
        await self.broadcast({"type": "steps", "steps": self.steps_status})

        # ---- N1 意图澄清（P1：授权 + 歧义消解） ----
        recipient = await self._n1(command)
        self.recipient = recipient

        # ---- ③ 计划生成 + ④ 计划预览（N2，含 P1 信任递进） ----
        await self.set_phase("PLANNING")
        send_clause = scripts.PLAN_THOUGHT_SEND if self.template == "SEND" \
            else scripts.PLAN_THOUGHT_ARCHIVE
        await self.stream(scripts.PLAN_THOUGHT.format(send_clause=send_clause))

        await self.set_phase("PLAN_REVIEW")
        plan_msg = {"steps": self._steps, "recipient": recipient,
                    "template": self.template}
        if self.template == "ARCHIVE" and self.trust_count >= 3:
            await self.stream(scripts.TRUST_AUTO.format(n=self.trust_count))
            await self.broadcast({**plan_msg, "type": "plan_auto"})
        else:
            await self.broadcast({**plan_msg, "type": "plan"})
            agree = await self._wait_plan()
            if not agree:
                await self.stream(scripts.PLAN_CANCELLED)
                await self._finish()
                return

        # ---- ⑤ 安全准备 ----
        await self.set_phase("BACKUP")
        await self.stream(scripts.BACKUP_THOUGHT.format(n=n_total))
        self.state.backup()
        await self._sync_env()
        await self.stream(scripts.BACKUP_DONE.format(n=n_total))

        # ---- ⑥ 分步执行（断言校验 + P1 重试 / N4） ----
        ok = await self._run_step(1, scripts.STEP1_THOUGHT,
                                  lambda: self.state.scan(), self._check_step1)
        if ok:
            ok = await self._run_step(2, scripts.STEP2_THOUGHT,
                                      lambda: self.state.extract(), self._check_step2)
        if ok:
            ok = await self._run_step(3, scripts.STEP3_THOUGHT,
                                      lambda: self.state.archive_files(),
                                      self._check_step3)
            if not ok:  # P1：断言失败 → 重试 1 次
                await self.stream(scripts.RETRY_MSG.format(
                    exp=self.n_expected, act=self.state.archived_count()))
                self.record.append({
                    "step": 3, "action": "断言失败 → 自动重试 1 次",
                    "assertion": self._steps[2]["assertion"], "result": "失败 ✗",
                    "detail": f"重试后仍为 {self.state.archived_count()} 个"
                              f"（1 个文件损坏无法读取）", "ms": 1200,
                })
                ok = await self._run_step(3, scripts.STEP3_RETRY,
                                          lambda: self.state.archive_files(),
                                          self._check_step3)
                if not ok:  # P1：重试仍失败 → N4 异常求助
                    await self.stream(scripts.RETRY_FAIL.format(
                        act=self.state.archived_count()))
                    await self.stream(scripts.HELP_INTRO)
                    await self.broadcast({"type": "help"})
                    choice = await self._wait_help()
                    if choice == "degrade":
                        self.n_expected = self.state.archived_count()
                        self.degraded = True
                        self.steps_status[2]["status"] = "done"
                        await self.broadcast(
                            {"type": "steps", "steps": self.steps_status})
                        self.record.append({
                            "step": 3, "action": "降级：跳过损坏文件",
                            "assertion": f"按 {self.n_expected} 个文件继续",
                            "result": "通过 ✓",
                            "detail": f"后续步骤（汇总/邮件）按 "
                                      f"{self.n_expected} 个文件执行", "ms": 300,
                        })
                        await self.stream(scripts.DEGRADE_OK.format(
                            n=self.n_expected))
                        ok = True
                    else:
                        await self.stream(scripts.ABORT.format(
                            act=self.state.archived_count(), n=n_total))
                        await self._finish()
                        return
        if ok:
            ok = await self._run_step(4, scripts.STEP4_THOUGHT,
                                      lambda: self.state.make_summary(),
                                      self._check_step4)
        if ok and self.template == "SEND":
            ok = await self._run_step(5, scripts.STEP5_THOUGHT,
                                      lambda: self._make_draft(), self._check_draft)
        if not ok:
            await self.stream("断言失败，任务安全中止（原件完好，隔离备份可用）。")
            await self._finish()
            return

        # ---- ⑦ 发送闸门（N3：路径 A 代发 | P1 路径 B 自主发送） ----
        if self.template == "SEND":
            draft = self.state.mail["drafts"][0]
            await self.set_phase("GATE")
            await self.stream(scripts.GATE_INTRO)
            await self.broadcast({
                "type": "gate", "to": draft["to"], "subject": draft["subject"],
                "attachments": draft["attachments"], "body": draft["body"],
            })
            mode = await self._wait_gate()
            if mode == "self":  # P1 路径 B
                await self.stream(scripts.SELF_EDIT_NOTE)
                await self.broadcast({"type": "self_edit", "draft": dict(draft)})
                edits = await self._wait_mail_send()
                sent = self.state.send_draft_edited(
                    edits.get("to"), edits.get("subject"), edits.get("body"))
                await self._sync_env()
                await self.stream(scripts.SELF_SENT.format(to=sent["to"]))
            else:  # 路径 A
                await self.stream(scripts.SENDING)
                await asyncio.sleep(0.8 / self.speed)
                self.state.send_draft()
                await self._sync_env()
                await self.stream(scripts.SENT_DONE)

        # ---- ⑧ 结果汇报 ----
        await self.set_phase("REPORTING")
        await self.broadcast({
            "type": "report", "text": self._report_text(),
            "table": self.state.summary_rows,
            "summary_name": self.state.summary_name,
        })
        await self.stream(scripts.REPORT_TAIL)

        # P1 信任递进：归档类任务成功后计数（含发送步骤的任务永不免确认）
        if self.template == "ARCHIVE":
            self.trust_count += 1

        # ---- ⑨ 用户验收与反馈（N5） ----
        await self.set_phase("FEEDBACK")
        try:
            await asyncio.wait_for(self._feedback_ev.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
        duration = round(time.time() - self.started_at, 1)
        await self.broadcast({
            "type": "stats", "duration_s": duration,
            "interventions": self.interventions,
            "steps": len(self.steps_status), "record": self.record,
            "trust": self.trust_count, "template": self.template,
        })
        await self._finish()

    # ---------------- P2：开放式指令多轮澄清 ----------------

    async def _multi_turn(self):
        await self.set_phase("CLARIFYING")
        await self.stream(scripts.MULTI_INTRO)
        for r in range(1, 4):
            await self.stream(scripts.MULTI_ASK.format(r=r))
            await self.broadcast({"type": "question",
                                  "quick": [scripts.MULTI_QUICK1,
                                            scripts.MULTI_QUICK2]})
            ans = await self._wait_answer() or ""
            if any(k in ans for k in CONVERGE_KEYS):
                await self.stream(scripts.MULTI_CONVERGED)
                return ans
            if r < 3:
                await self.stream(scripts.MULTI_PROGRESS.format(ans=ans[:40]))
        await self.stream(scripts.MULTI_REJECT)
        return None

    # ---------------- N1：意图澄清（P1 授权 / 歧义消解） ----------------

    async def _n1(self, command):
        await self.set_phase("CLARIFYING")
        if self.template == "ARCHIVE":
            await self.stream(scripts.N1_SKIP)
            return None

        await self.stream(scripts.UNDERSTAND)
        mention = next((c["name"] for c in CONTACTS if c["name"] in command), None)
        recipient = None

        if mention:
            if self.auth_granted is None:
                await self.stream(scripts.AUTH_NOTE.format(name=mention))
                await self.broadcast({"type": "auth_ask"})
                granted = await self._wait_auth()
            else:
                granted = self.auth_granted
            if granted:
                await self.stream(scripts.AUTH_RESOLVING.format(name=mention))
                cands = [c for c in CONTACTS if c["name"] == mention]
                if len(cands) == 1:
                    recipient = cands[0]["email"]
                    await self.stream(scripts.CONTACT_UNIQUE.format(
                        name=mention, dept=cands[0]["dept"], email=recipient))
                else:
                    await self.stream(scripts.CONTACT_AMBIGUOUS.format(
                        name=mention, n=len(cands)))
                    await self.broadcast({"type": "question", "quick": [
                        f"{c['name']}（{c['dept']}）{c['email']}" for c in cands]})
                    ans = await self._wait_answer() or ""
                    for c in cands:
                        if c["dept"] in ans or c["email"] in ans:
                            recipient = c["email"]
                            break
                    if recipient:
                        await self.stream(
                            scripts.CONTACT_PICKED.format(email=recipient))
            else:
                await self.stream(scripts.AUTH_DENIED)

        if recipient is None:
            email = None
            for _ in range(2):
                await self.stream(scripts.ASK_EMAIL)
                await self.broadcast({"type": "question",
                                      "quick": [scripts.QUICK_REPLY_EMAIL]})
                ans = await self._wait_answer()
                m = EMAIL_RE.search(ans or "")
                if m:
                    email = m.group(0)
                    break
                await self.stream(scripts.ASK_EMAIL_AGAIN)
            recipient = email or scripts.QUICK_REPLY_EMAIL

        await self.stream(scripts.N1_CONFIRM.format(email=recipient))
        return recipient

    # ---------------- 步骤执行辅助 ----------------

    def _plan_steps(self):
        n = len(self.state.invoices)
        steps = [
            {"id": 1, "name": "扫描下载目录，识别发票文件",
             "assertion": "找到 ≥1 个发票文件"},
            {"id": 2, "name": "提取金额 / 日期 / 对方单位",
             "assertion": "字段完整率 ≥ 90%"},
            {"id": 3, "name": "备份原件 → 按月份归档重命名",
             "assertion": f"归档 {n} 个重命名文件，备份数 = {n}"},
            {"id": 4, "name": "生成汇总表《发票汇总-2026-09.xlsx》",
             "assertion": f"文件存在且行数 = {n}"},
        ]
        if self.template == "SEND":
            steps.append({"id": 5, "name": "起草邮件（附件已挂）→ 闸门 → 发送",
                          "assertion": "草稿收件人 = 指定邮箱"})
        return steps

    async def _run_step(self, idx, thought, fn, check):
        st = self.steps_status[idx - 1]
        st["status"] = "running"
        await self.set_phase("EXECUTING")
        await self.broadcast({"type": "steps", "steps": self.steps_status})
        await self.stream(thought)
        t0 = time.time()
        fn()
        await self._sync_env()
        ok, actual = check()
        dur = max(int((time.time() - t0) * 1000), 200)
        self.record.append({
            "step": idx, "action": self._steps[idx - 1]["name"],
            "assertion": self._steps[idx - 1]["assertion"],
            "result": "通过 ✓" if ok else "失败 ✗",
            "detail": actual, "ms": dur,
        })
        st["status"] = "done" if ok else "failed"
        await self.broadcast({"type": "steps", "steps": self.steps_status})
        await self.stream(("✓ " if ok else "✗ ") + actual)
        await asyncio.sleep(0.4 / self.speed)
        return ok

    def _check_step1(self):
        n = len(self.state.found)
        d = len(self.state.damaged)
        text = f"已找到 {n} 个发票文件（断言：≥1 ✓）"
        if d:
            text += f"，其中 {d} 个疑似损坏"
        return n >= 1, text

    def _check_step2(self):
        rows = self.state.extract()
        n_total = len(self.state.invoices)
        rate = len(rows) / n_total if n_total else 0
        ok = rate >= 0.9
        text = (f"字段完整率 {rate:.0%}（{len(rows)}/{n_total}："
                f"金额、日期、对方单位 {'✓' if ok else '✗'}）")
        return ok, text

    def _check_step3(self):
        act = self.state.archived_count()
        ok = act == self.n_expected and len(self.state.backup_files) >= act
        text = (f"归档 {act} 个重命名文件，隔离备份 "
                f"{len(self.state.backup_files)} 个（断言："
                f"{'✓' if ok else '✗ 预期 ' + str(self.n_expected)}）")
        return ok, text

    def _check_step4(self):
        rows = self.state.summary_rows
        ok = len(rows) == self.n_expected
        return ok, (f"汇总表已生成，行数 = {len(rows)}"
                    f"（断言：= {self.n_expected} {'✓' if ok else '✗'}）")

    def _make_draft(self):
        invs = [i for i in self.state.invoices
                if i["源文件"] not in self.state.damaged]
        n = len(invs)
        total = sum(i["金额"] for i in invs)
        months = sorted({i["日期"][:7] for i in invs})
        parts = "，".join(
            f"{m}：{sum(1 for i in invs if i['日期'].startswith(m))} 张"
            for m in months)
        attachments = sorted(
            f for v in self.state.archive.values() for f in v)
        damaged_note = (f"\n（另有 {len(self.state.damaged)} 个损坏文件已跳过，"
                        f"保留在下载目录）") if self.degraded else ""
        body = "\n".join([
            "你好：",
            "",
            f"附件是整理好的 {n} 张发票（{parts}），合计金额 ¥{total:,.2f}。",
            f"汇总明细见附件《{self.state.summary_name}》，原件已按月份归档。"
            + damaged_note,
            "",
            "如有问题随时联系。",
            "",
            "—— 由 AI 助手代为整理",
        ])
        subject = f"【AI 助手整理】发票汇总（{n} 张，合计 ¥{total:,.2f}）"
        self.state.make_draft(self.recipient, subject, attachments, body)

    def _check_draft(self):
        drafts = self.state.mail["drafts"]
        if not drafts:
            return False, "草稿不存在（断言 ✗）"
        d = drafts[0]
        ok = d["to"] == self.recipient and len(d["attachments"]) == self.n_expected
        return ok, (f"草稿已创建，收件人 = {d['to']}，"
                    f"附件 {len(d['attachments'])} 个（断言 {'✓' if ok else '✗'}）")

    def _report_text(self):
        invs = [i for i in self.state.invoices
                if i["源文件"] not in self.state.damaged]
        n = len(invs)
        total = sum(i["金额"] for i in invs)
        months = sorted({i["日期"][:7] for i in invs})
        parts = "，".join(
            f"{m} {sum(1 for i in invs if i['日期'].startswith(m))} 张"
            for m in months)
        text = (f"已整理 {n} 张发票并归档至 ~/Documents/发票/（{parts}），"
                f"汇总表：~/Documents/{self.state.summary_name}")
        if self.degraded:
            text += (f"（{len(self.state.damaged)} 个损坏文件已跳过，"
                     f"保留在下载目录）")
        if self.template == "SEND":
            text += f"，邮件已发送给 {self.recipient}。"
        else:
            text += "。"
        text += f"合计金额 ¥{total:,.2f}。"
        return text
