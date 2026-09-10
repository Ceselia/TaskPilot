"""WebSocket 事件录制脚本：将一次完整演示的事件流录制为 timeline.json。

用法：
    python record_events.py              # 默认录制到 data/timeline.json
    python record_events.py -o custom.json
    python record_events.py --scenario p1  # 不同场景
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, ".")

from server.engine import Engine
from server.seed import seed


class TimelineRecorder:
    """事件录制器：捕获并序列化WebSocket事件为时间轴。"""
    
    def __init__(self):
        self.events = []
        self.start_time = datetime.now()
        self.phase_transitions = []
    
    async def send_json(self, msg):
        """模拟 WebSocket send_json，记录事件。"""
        timestamp = (datetime.now() - self.start_time).total_seconds()
        event_record = {
            "timestamp": round(timestamp * 1000),  # 毫秒
            "type": msg.get("type"),
            "data": msg
        }
        self.events.append(event_record)
        
        # 记录阶段转换
        if msg.get("type") == "phase":
            self.phase_transitions.append({
                "phase": msg.get("phase"),
                "timestamp": event_record["timestamp"]
            })
    
    def to_dict(self):
        """导出为字典格式。"""
        return {
            "version": "1.0",
            "generated_at": self.start_time.isoformat(),
            "total_duration_ms": self.events[-1]["timestamp"] if self.events else 0,
            "events": self.events,
            "phase_transitions": self.phase_transitions,
            "playback_speed": 1.0  # 前端回放速度系数
        }


async def auto_drive(engine, cmd, answers=(), scenario="basic"):
    """自动应答驱动器。"""
    answers = list(answers)
    engine.task = asyncio.create_task(engine.run(cmd))
    engine.speed = 30  # 适度减速，便于录制观察
    
    while not engine.task.done():
        await asyncio.sleep(0.01)
        a = engine.awaiting
        
        if a == "answer" and answers:
            engine.submit_answer(answers.pop(0))
        elif a == "auth" and scenario == "p1":
            engine.submit_auth(True)  # P1 场景允许授权
        elif a == "plan":
            engine.confirm_plan(True)
        elif a == "gate":
            if scenario == "p1_self":
                engine.gate_confirm("self")
            else:
                engine.gate_confirm("send")
        elif a == "mail_send" and scenario == "p1_self":
            engine.submit_mail_send({})
        elif a is None and engine.phase == "FEEDBACK":
            engine.submit_feedback("good")
    
    await engine.task


async def record_scenario(scenario="basic", output_path="data/timeline.json"):
    """录制指定场景。
    
    场景：
    - basic: P0 基础发票流程
    - p1: P1 授权 + 歧义消解
    - p1_self: P1 用户自主编辑发送
    """
    seed()
    engine = Engine()
    recorder = TimelineRecorder()
    engine.clients.add(recorder)
    
    if scenario == "basic":
        cmd = "把下载目录里的发票整理一下，汇总个表发给张三。"
        answers = ["zhangsan@example.com，按月份归档"]
    elif scenario == "p1":
        cmd = "把下载目录里的发票整理一下，汇总个表发给张三。"
        answers = ["张三（市场部）zhangsan@market.com"]
    elif scenario == "p1_self":
        cmd = "把下载目录里的发票整理一下，汇总个表发给李四。"
        answers = ["lisi@example.com"]
    else:
        cmd = "把下载目录里的发票整理一下，汇总个表发给张三。"
        answers = []
    
    await auto_drive(engine, cmd, answers=answers, scenario=scenario)
    
    # 保存为JSON
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    timeline = recorder.to_dict()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 录制完成：{output_path}")
    print(f"  - 总事件数：{len(timeline['events'])}")
    print(f"  - 总时长：{timeline['total_duration_ms']}ms")
    print(f"  - 阶段转换数：{len(timeline['phase_transitions'])}")
    
    return output_path


async def main():
    import argparse
    
    ap = argparse.ArgumentParser(description="WebSocket 事件录制")
    ap.add_argument("-o", "--output", default="data/timeline.json",
                    help="输出JSON文件路径")
    ap.add_argument("--scenario", default="basic",
                    choices=["basic", "p1", "p1_self"],
                    help="录制场景")
    args = ap.parse_args()
    
    await record_scenario(scenario=args.scenario, output_path=args.output)


if __name__ == "__main__":
    asyncio.run(main())
