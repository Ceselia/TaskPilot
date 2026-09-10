"""FastAPI 应用：REST（用户动作）+ WebSocket（流式事件推送）+ 静态前端。"""
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import Engine
from .seed import seed

seed()

app = FastAPI(title="「一句话代办」演示 Demo")
engine = Engine()

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class TextBody(BaseModel):
    text: str


class AgreeBody(BaseModel):
    agree: bool = True


class ControlBody(BaseModel):
    action: str   # pause | resume | speed


class FeedbackBody(BaseModel):
    kind: str     # good | bad


class AuthBody(BaseModel):          # P1：通讯录授权弹窗
    grant: bool


class GateBody(BaseModel):          # P1：闸门路径 A（代发）/ 路径 B（自主发送）
    mode: str = "send"              # send | self


class MailSendBody(BaseModel):      # P1 路径 B：用户自主编辑后发送
    to: str = ""
    subject: str = ""
    body: str = ""


class InjectBody(BaseModel):        # P1：故障注入开关
    on: bool


class HelpBody(BaseModel):          # P1 N4：降级 / 安全中止
    choice: str                     # degrade | abort


@app.post("/api/command")
async def command(body: TextBody):
    if engine.task and not engine.task.done():
        raise HTTPException(status_code=409, detail="已有任务在执行中")
    engine.task = asyncio.create_task(engine.run(body.text))
    return {"ok": True}


@app.post("/api/answer")
async def answer(body: TextBody):
    engine.submit_answer(body.text)
    return {"ok": True}


@app.post("/api/plan")
async def plan(body: AgreeBody):
    engine.confirm_plan(body.agree)
    return {"ok": True}


@app.post("/api/gate")
async def gate(body: GateBody):
    engine.gate_confirm(body.mode)
    return {"ok": True}


@app.post("/api/auth")
async def auth(body: AuthBody):
    engine.submit_auth(body.grant)
    return {"ok": True}


@app.post("/api/mail/send")
async def mail_send(body: MailSendBody):
    engine.submit_mail_send(
        {"to": body.to, "subject": body.subject, "body": body.body})
    return {"ok": True}


@app.post("/api/inject")
async def inject(body: InjectBody):
    engine.set_inject(body.on)
    await engine.broadcast({"type": "inject_state", "on": body.on})
    return {"ok": True, "on": body.on}


@app.post("/api/help")
async def help_(body: HelpBody):
    engine.submit_help(body.choice)
    return {"ok": True}


@app.post("/api/feedback")
async def feedback(body: FeedbackBody):
    engine.submit_feedback(body.kind)
    return {"ok": True}


@app.post("/api/control")
async def control(body: ControlBody):
    engine.control(body.action)
    return {"ok": True, "speed": engine.speed}


@app.post("/api/reset")
async def reset():
    engine.reset()
    await engine.broadcast({"type": "reset"})
    return {"ok": True}


@app.get("/api/state")
async def state():
    return {
        "phase": engine.phase,
        "running": bool(engine.task and not engine.task.done()),
        "speed": engine.speed,
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await engine.register(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        engine.clients.discard(ws)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
