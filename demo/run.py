"""「一句话代办」演示 Demo 启动入口。

用法：
    python run.py                # 启动并自动打开浏览器
    python run.py --port 8001    # 指定端口
    python run.py --no-browser   # 不自动打开浏览器
"""
import argparse
import threading
import webbrowser

import uvicorn

from server.seed import seed


def main():
    ap = argparse.ArgumentParser(description="「一句话代办」可交互演示 Demo")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    seed()  # 首次运行时生成 12 个结构化模拟发票文件
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    print(f"Demo 运行中: {url}  （Ctrl+C 退出）")
    uvicorn.run("server.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
