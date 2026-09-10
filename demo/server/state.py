"""虚拟环境状态：虚拟文件系统 + 虚拟通讯录 + 虚拟邮件客户端（全模拟，不触碰真实系统）。"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "invoices"

# P1：虚拟通讯录（两个张三用于演示歧义消解）
CONTACTS = [
    {"name": "张三", "dept": "市场部", "email": "zhangsan@market.com"},
    {"name": "张三", "dept": "财务部", "email": "zhangsan@finance.com"},
    {"name": "李四", "dept": "行政部", "email": "lisi@corp.com"},
]


def load_invoices():
    out = []
    for f in sorted(DATA_DIR.glob("invoice_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        d["源文件"] = f.name
        out.append(d)
    return out


def _arch_name(inv):
    return f"{inv['日期']}_{inv['对方单位']}_{inv['金额']:g}元.json"


class VirtualState:
    """内存态虚拟环境：文件系统三处（下载/归档/隔离备份）+ 通讯录 + 邮件客户端。

    P1 故障注入：damaged 集合中的文件模拟「损坏无法读取」，
    提取与归档均跳过，文件保留在下载目录。
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.invoices = load_invoices()
        self.download = [inv["源文件"] for inv in self.invoices]
        self.backup_files = []
        self.archive = {}          # "2026-08" -> [重命名后的文件]
        self.summary_name = None
        self.summary_rows = []
        self.found = []
        self.damaged = set()       # P1：损坏文件（故障注入）
        self.mail = {
            "inbox": [
                {"id": 1, "frm": "李四 <lisi@corp.com>", "subject": "周报提醒",
                 "body": "记得周五前提交本周周报。", "attachments": []},
                {"id": 2, "frm": "财务部 <finance@corp.com>", "subject": "9月报销截止通知",
                 "body": "本月报销单据请于 9 月 25 日前提交，逾期顺延至下月。", "attachments": []},
            ],
            "drafts": [],
            "sent": [],
        }
        self._mail_seq = 2

    # ---------- 文件系统操作 ----------

    def scan(self):
        self.found = list(self.download)
        return self.found

    def extract(self):
        return [
            {"文件名": inv["源文件"], "对方单位": inv["对方单位"],
             "金额": inv["金额"], "日期": inv["日期"]}
            for inv in self.invoices
            if inv["源文件"] in self.found and inv["源文件"] not in self.damaged
        ]

    def backup(self):
        self.backup_files = list(self.download)

    def archive_files(self):
        for inv in self.invoices:
            name = inv["源文件"]
            if name in self.download and name not in self.damaged:
                self.download.remove(name)
                month = inv["日期"][:7]
                self.archive.setdefault(month, []).append(_arch_name(inv))
        for v in self.archive.values():
            v.sort()

    def archived_count(self):
        return sum(len(v) for v in self.archive.values())

    def make_summary(self):
        self.summary_name = "发票汇总-2026-09.xlsx"
        self.summary_rows = sorted(self.extract(), key=lambda r: r["日期"])

    # ---------- 邮件操作 ----------

    def make_draft(self, to, subject, attachments, body):
        self._mail_seq += 1
        draft = {"id": self._mail_seq, "to": to, "subject": subject,
                 "attachments": attachments, "body": body}
        self.mail["drafts"].append(draft)
        return draft

    def send_draft(self):
        d = self.mail["drafts"].pop(0)
        self.mail["sent"].append(d)
        return d

    def send_draft_edited(self, to=None, subject=None, body=None):
        """P1 路径 B：用户自主修改草稿后亲自发送，应用编辑内容并移入已发送。"""
        d = self.mail["drafts"].pop(0)
        if to:
            d["to"] = to
        if subject:
            d["subject"] = subject
        if body:
            d["body"] = body
        d["self_sent"] = True
        self.mail["sent"].append(d)
        return d

    # ---------- 快照 ----------

    def fs_snapshot(self):
        return {
            "download": list(self.download),
            "archive": {k: list(v) for k, v in self.archive.items()},
            "backup": list(self.backup_files),
            "summary": self.summary_name,
        }

    def mail_snapshot(self):
        return {
            "inbox": [dict(m) for m in self.mail["inbox"]],
            "drafts": [dict(m) for m in self.mail["drafts"]],
            "sent": [dict(m) for m in self.mail["sent"]],
        }
